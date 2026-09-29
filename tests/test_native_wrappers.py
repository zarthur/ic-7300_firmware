"""Actual patched call sites, original queue/publication flow and snapshot bounds."""
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import native_wrappers as wrapper
from emulate_platform import APP_BASE, inputs
from native_capture import decode_storage
from native_transport import recover


class SyntheticWrapperTests(unittest.TestCase):
    def test_bundle_and_exact_image_gate(self):
        code,entries=wrapper.build_bundle()
        self.assertLess(len(code),8192)
        self.assertEqual(set(entries),set(wrapper.SITES))
        with self.assertRaisesRegex(ValueError,'exact pinned'):wrapper.patches(b'unknown')

    def test_source_mutation_invalidates_evidence(self):
        for change in ('image','restored_image','tool','revision',None):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                image=Path(directory)/'image';image.write_bytes(b'initial')
                initial=wrapper.digest(image.read_bytes())
                def evaluate(path):
                    if change in ('image','restored_image'):
                        path.write_bytes(b'changed')
                        if change=='restored_image':path.write_bytes(b'initial')
                    return {'image_sha256':initial}
                with patch.object(wrapper,'_report',side_effect=evaluate), \
                        patch.object(wrapper,'tool_hashes',side_effect=[{'t':'before'},{'t':'after' if change=='tool' else 'before'}]), \
                        patch('firmware.revision',side_effect=['before','after' if change=='revision' else 'before']):
                    if change:
                        with self.assertRaisesRegex(ValueError,'changed'):wrapper.report(image)
                    else:self.assertTrue(wrapper.report(image)['source_unchanged'])

    def test_arm_and_interworking_call_encodings(self):
        self.assertEqual(wrapper.arm_call(0x1000,0x1008).hex(),'000000eb')
        self.assertEqual(wrapper.arm_call(0x1000,0x1000).hex(),'feffffeb')
        self.assertEqual(wrapper.arm_call(0x1000,0x100a,True).hex(),'000000fb')
        for site,target in ((1,0x1000),(0x1000,1),(-4,0x1000),(0x1000,1<<32),(0,1<<26)):
            with self.assertRaises(ValueError):wrapper.arm_call(site,target)


def samples(index):
    a=[(index+j*97)%65536-32768 for j in range(36)]
    b=[32767-(index+j*113)%65536 for j in range(36)]
    words=b''.join(struct.pack('<4I',((x&65535)<<16)|0xabcd,((y&65535)<<16)|0x1234,
                               0xdeadbeef,0xcafefeed) for x,y in zip(a,b))
    return words,a,b


IMAGE=os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'),'Opt-in pinned image and Unicorn required')
class FirmwareWrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):_,_,cls.app,_=inputs(Path(IMAGE))

    def test_actual_dma_hook_preserves_queue_inputs_flags_and_native_outputs(self):
        for bank in (0,1):
            for status in (0,1,2,3,4):
                with self.subTest(bank=bank,status=status):
                    trials=[wrapper.WrapperTrial(self.app,'dma',patched=value) for value in (False,True)]
                    call_states=[];results=[]
                    for trial in trials:
                        trial.configure(status=status)
                        states=[]
                        regs=[getattr(trial.a,'UC_ARM_REG_R'+str(i)) for i in range(13)]
                        regs += [trial.a.UC_ARM_REG_SP,trial.a.UC_ARM_REG_LR,trial.a.UC_ARM_REG_APSR]
                        def at_queue(uc,address,size,user):
                            if address==0x2005fb28:states.append([uc.reg_read(r) for r in regs])
                        trial.uc.hook_add(trial.u.UC_HOOK_CODE,at_queue)
                        result=trial.dma(samples(17)[0],bank)
                        results.append(result);call_states.append(states)
                    self.assertEqual(call_states[0],call_states[1])
                    for key in ('queue_a','queue_b','split'):self.assertEqual(results[0][key],results[1][key])
                    self.assertEqual(len(results[1]['observations']),6 if status==1 else 0)
                    self.assertLessEqual(results[1]['stack_extra_bytes'],88)
                    if status==1:
                        decoded=decode_storage(trials[1].storage())
                        self.assertEqual(decoded['records'][0]['observations'],[1,32000,0,1,31990,0,wrapper.DMA+576*(bank+1)])

    def test_register_guard_rejects_subword_writes_and_reads(self):
        trial=wrapper.WrapperTrial(self.app,'dma')
        entry=trial.entries['dma']
        # Deliberately replace the first diagnostic instruction in this private
        # fixture: STRB r0,[r1], then LDRH r0,[r1]. No candidate uses these bytes.
        for instruction,pattern in ((0xe5c10000,'wrote timer'),(0xe1d100b0,'observation width')):
            trial.uc.mem_write(entry,struct.pack('<I',instruction))
            for base in (wrapper.TICK,wrapper.COUNTER,wrapper.PENDING):
                with self.subTest(instruction=instruction,base=base):
                    with self.assertRaisesRegex(ValueError,pattern):
                        trial.h.run(entry,(1,base+1),stop=entry+4)

    def test_actual_trigger_preserves_submit_and_never_rearms(self):
        for status,count,index,transport_status,length in ((0,0,0,0,216),(0,0,0,0,0),(1,0,0,0,216),
                (2,512,470,2,216),(3,0,0,0,216),(4,0,0,0,216),(0,1,0,0,216),(0,0,1,0,216),(0,0,0,1,216)):
            with self.subTest(state=(status,count,index,transport_status,length)):
                results=[];trials=[]
                for patched in (False,True):
                    trial=wrapper.WrapperTrial(self.app,'arm',patched=patched)
                    trial.configure(status,count,index,transport_status)
                    trials.append(trial);results.append(trial.arm(length))
                self.assertEqual(results[0]['record_state'],results[1]['record_state'])
                self.assertEqual(results[0]['arguments'],results[1]['arguments'])
                expected=1 if (status,count,index,transport_status,length)==(0,0,0,0,216) else status
                self.assertEqual(struct.unpack_from('<I',trials[1].storage())[0],expected)
                self.assertEqual(trials[1].storage()[4:],trials[0].storage()[4:])
                self.assertEqual(trials[1].control(),(index,transport_status))

    def test_inactive_carrier_matches_original_publisher(self):
        for index in (0,1913):
            for enabled in (0,1):
                for status,transport_status in ((0,0),(1,0),(2,2),(3,0),(4,0)):
                    with self.subTest(index=index,enabled=enabled,status=status):
                        results=[]
                        for patched in (False,True):
                            trial=wrapper.WrapperTrial(self.app,'carrier',patched=patched)
                            trial.configure(status,512 if status==2 else 0,470 if transport_status==2 else 0,transport_status)
                            before=trial.storage()
                            results.append(trial.publish(index,enabled=enabled))
                            self.assertEqual(trial.storage(),before)
                        for key in ('ring','index_after','fill_after'):self.assertEqual(results[0][key],results[1][key])

    def test_full_actual_hook_capture_and_carrier_roundtrip(self):
        dma=wrapper.WrapperTrial(self.app,'dma');dma.configure(status=1)
        for i in range(512):
            # Explicit observations cross counter/epoch boundaries; no claim that
            # synthetic register contents model real timer or interrupt behavior.
            observation=[(0xfffffff0+i)&0xffffffff,1,0, (0xfffffff1+i)&0xffffffff,32000,0x40]
            dma.dma(samples(i)[0],i%2,observation)
        storage=dma.storage();decoded=decode_storage(storage)
        self.assertEqual((decoded['status'],decoded['count']),(2,512))
        for i,row in enumerate(decoded['records']):
            _,a,b=samples(i)
            self.assertEqual(row['stream_a'],a);self.assertEqual(row['stream_b'],b)
            self.assertEqual(row['observations'],[(0xfffffff0+i)&0xffffffff,1,0,(0xfffffff1+i)&0xffffffff,32000,0x40,wrapper.DMA+576*(i%2+1)])
        dma.dma(samples(513)[0]);self.assertEqual(dma.storage(),storage)
        self.assertEqual(dma.reads,[])
        carrier=wrapper.WrapperTrial(self.app,'carrier')
        carrier.uc.mem_write(wrapper.CAPTURE,storage)
        frames=[]
        for n in range(470):
            index=(1913+n)%1914
            row=carrier.publish(index)
            self.assertEqual(row['index_after'],(index+1)%1914)
            self.assertEqual(row['fill_after'],0)
            slot=row['ring'][index*220:(index+1)*220]
            self.assertEqual(slot[:4],b'\xa5\x5a\x01\xa5');frames.append(slot[4:])
        self.assertEqual(recover(b''.join(frames)),storage)
        self.assertEqual(carrier.control(),(470,2))
        self.assertEqual(carrier.storage(),storage)
        self.assertEqual(carrier.publish(500)['ring'][500*220+4:501*220],bytes(range(216)))

    def test_patch_footprint_is_limited_to_calls_and_padding(self):
        edits=wrapper.patches(self.app)
        spans=[]
        for address,data in edits:
            spans.append((address,address+len(data)))
            self.assertTrue(address in [s[0] for s in wrapper.SITES.values()] or 0x2036166c<=address<address+len(data)<=0x20390000)
        ordered=sorted(spans)
        self.assertTrue(all(a[1]<=b[0] for a,b in zip(ordered,ordered[1:])))
        self.assertEqual(len(edits),6)
        changed=bytearray(self.app);changed[0]^=1
        with self.assertRaisesRegex(ValueError,'exact pinned'):wrapper.patches(bytes(changed))


if __name__=='__main__':unittest.main()
