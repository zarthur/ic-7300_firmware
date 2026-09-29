"""Exercise combined v2 recorder, capture and lifecycle hooks on original paths."""
import importlib.util
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from emulate_platform import APP_BASE, STACK, inputs
from native_capture_v2 import MAGIC, VERSION, STORAGE_SIZE, decode_storage
from native_transport_v2 import recover, FRAME_COUNT
import native_v2_recorder as combined


class SyntheticV2RecorderTests(unittest.TestCase):
    def test_combined_components_and_unknown_image_gate(self):
        blobs,entries = combined.build_bundle()
        self.assertEqual([len(code) for _,code in blobs], [1508,380,688])
        self.assertEqual(set(entries), {'capture','lifecycle','recorder'})
        with self.assertRaisesRegex(ValueError,'exact pinned'): combined.offline_edits(b'unknown')


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'),'Pinned image and Unicorn required')
class FirmwareV2RecorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,_,cls.app,_ = inputs(Path(IMAGE))
        cls.words = b''.join(struct.pack('<4I',(i*97)<<16,(65535-i*113)<<16,0xdeadbeef,0xcafefeed) for i in range(36))

    def reset(self,trial,status=0,count=0,magic=MAGIC,version=VERSION,live=(0,)*8,control=(0,0)):
        trial.uc.mem_write(combined.CAPTURE,struct.pack('<4I',status,count,magic,version))
        trial.uc.mem_write(combined.LIVE,struct.pack('<8I',*live))
        trial.uc.mem_write(combined.CONTROL,struct.pack('<2I',*control))

    def interleave(self,trial,call):
        # Explicit isolated context switch, not modeled hardware IRQ delivery.
        cpu = trial.uc.context_save()
        stack = bytes(trial.uc.mem_read(STACK+0xee00,512))
        bank = trial.ready_bank
        result = call()
        trial.uc.mem_write(STACK+0xee00,stack)
        trial.uc.context_restore(cpu)
        trial.ready_bank = bank
        return result

    def test_arm_preserves_original_submit_and_rejects_nonidle_state(self):
        fixtures = [(dict(),216,True),(dict(),0,False)]
        fixtures += [(dict(status=status),216,False) for status in (1,2,3,4,5,6,0xffffffff)]
        fixtures += [(dict(count=1),216,False),(dict(magic=0),216,False),(dict(version=1),216,False)]
        fixtures += [(dict(control=state),216,False) for state in ((1,0),(0,1),(598,2),(0,3))]
        fixtures += [(dict(live=tuple(1 if i==field else 0 for i in range(8))),216,False) for field in range(4)]
        baseline,trial = combined.CombinedTrial(self.app,False),combined.CombinedTrial(self.app)
        states = [[],[]]
        for n,t in enumerate((baseline,trial)):
            def at_submit(uc,address,size,user,n=n,t=t):
                if address==0x2006a354:
                    states[n].append(t._registers()+[uc.reg_read(t.a.UC_ARM_REG_SP),uc.reg_read(t.a.UC_ARM_REG_LR),uc.reg_read(t.a.UC_ARM_REG_CPSR)])
            t.uc.hook_add(t.u.UC_HOOK_CODE,at_submit)
        for fixture,length,armed in fixtures:
            for flags in (0,0xf80f0000):
                for masks in (0,0x40,0x80,0xc0):
                    rows=[]
                    for t in (baseline,trial):
                        self.reset(t,**fixture)
                        t.uc.reg_write(t.a.UC_ARM_REG_CPSR,0x13|flags|masks)
                        for i in range(13): t.uc.reg_write(getattr(t.a,'UC_ARM_REG_R'+str(i)),0x12340000+i)
                        rows.append(t.arm(length))
                    self.assertEqual(states[0][-1],states[1][-1])
                    self.assertEqual(rows[0]['record_state'],rows[1]['record_state'])
                    self.assertEqual(rows[0]['arguments'],rows[1]['arguments'])
                    self.assertEqual(struct.unpack_from('<I',trial.storage())[0],1 if armed else fixture.get('status',0))
                    self.assertEqual(trial.storage()[4:],baseline.storage()[4:])
                    self.assertEqual(trial.live(),baseline.live())
                    self.assertEqual(trial.control(),baseline.control())

    def test_lifecycle_relocation_preserves_prologues_and_frozen_storage(self):
        trial = combined.CombinedTrial(self.app)
        for status in (0,2,5,6):
            self.reset(trial,status=status,count=512 if status==2 else int(status==5))
            frozen = trial.storage()
            for reason,kind in enumerate(combined.epoch.SITES,1):
                for flags in (0,0xf80f0000):
                    for mask in (0,0x40,0x80,0xc0):
                        for before in ((0,0,0,0),(37,2,0,7),(0xffffffff,1,0,7),(37,2,1,7)):
                            trial.uc.mem_write(combined.EPOCH,struct.pack('<4I',*before))
                            result=trial.lifecycle(kind,flags|mask)
                            expected=before if before[2] else (before[0],before[1],1,before[3]) if before[0]==0xffffffff else (before[0]+1,reason,0,before[3])
                            self.assertEqual(result['epoch'],expected)
                            self.assertEqual(trial.storage(),frozen)

    def test_combined_arm_capture_epoch_change_export_and_no_rearm(self):
        trial=combined.CombinedTrial(self.app)
        trial.configure(status=0,epoch=(0,0,0))
        self.assertEqual(trial.lifecycle('cold')['epoch'],(1,1,0,0))
        self.assertEqual(trial.lifecycle('start')['epoch'],(2,4,0,0))
        trial.arm()
        for i in range(512):
            trial.decision(0xc1 if i%2==0 else 0x41)
            if i==17: self.interleave(trial,lambda: trial.lifecycle('stop'))
            if i==18: self.interleave(trial,lambda: trial.lifecycle('start'))
            trial.ready(self.words)
        frozen=trial.storage();decoded=decode_storage(frozen)
        self.assertEqual((decoded['status'],decoded['count']),(2,512))
        for i,row in enumerate(decoded['records']):
            self.assertEqual(row['flags'],1 if i in (17,18) else 0)
            self.assertEqual(row['observations'][6],combined.DMA+576*(i%2+1))
        self.assertEqual(decoded['records'][17]['epoch_before'],[2,4,0])
        self.assertEqual(decoded['records'][17]['epoch_after'],[3,3,0])
        frames=[]
        for n in range(FRAME_COUNT):
            index=(1913+n)%1914
            row=trial.publish(index)
            slot=row['ring'][index*220:(index+1)*220]
            self.assertEqual(slot[:4],b'\xa5\x5a\x01\xa5')
            self.assertEqual(row['index_after'],(index+1)%1914)
            self.assertEqual(row['fill_after'],0)
            frames.append(slot[4:])
        self.assertEqual(recover(b''.join(frames)),frozen)
        self.assertEqual(trial.control(),(598,2))
        trial.arm();trial.lifecycle('restart')
        trial.decision(0xc1);trial.ready(self.words)
        self.assertEqual(trial.storage(),frozen)
        self.assertEqual(trial.timer_reads,[])
        self.assertEqual(trial.publish(10)['ring'][10*220+4:11*220],bytes(range(216)))

    def test_nested_cancel_exports_explicit_empty_abort(self):
        trial=combined.CombinedTrial(self.app);trial.configure(status=0)
        trial.arm()
        # Pause outer entry after begin, before the status test; run one nested
        # idle callback, then let the outer callback take its idle/cancel exit.
        stopped=[False]
        def pause(uc,address,size,user):
            if address==0x20060618 and not stopped[0]: stopped[0]=True;uc.emu_stop()
        handle=trial.uc.hook_add(trial.u.UC_HOOK_CODE,pause)
        with self.assertRaisesRegex(ValueError,'decision boundary'): trial.decision(1)
        trial.uc.hook_del(handle)
        self.interleave(trial,lambda: trial.decision(1))
        trial.uc.emu_start(0x20060618,combined.RETURN,count=1000,timeout=1000000)
        self.assertEqual(trial.uc.reg_read(trial.a.UC_ARM_REG_PC),combined.RETURN)
        frozen=trial.storage()
        self.assertEqual((decode_storage(frozen)['status'],decode_storage(frozen)['count']),(6,0))
        frames=[trial.publish(i)['ring'][i*220+4:(i+1)*220] for i in range(FRAME_COUNT)]
        self.assertEqual(recover(b''.join(frames)),frozen)
        self.assertEqual(trial.control(),(598,2))

    def test_nested_ready_abort_and_shared_restart_continue_through_real_hooks(self):
        trial=combined.CombinedTrial(self.app);trial.configure(status=0)
        trial.arm();trial.decision(0xc1)
        self.interleave(trial,lambda: trial.decision(1))
        trial.ready(self.words)
        frozen=trial.storage();decoded=decode_storage(frozen)
        self.assertEqual((decoded['status'],decoded['count'],decoded['records'][0]['flags']),(5,1,8))
        frames=[trial.publish(i)['ring'][i*220+4:(i+1)*220] for i in range(FRAME_COUNT)]
        self.assertEqual(recover(b''.join(frames)),frozen)
        trial=combined.CombinedTrial(self.app);trial.configure(status=0,epoch=(7,4,0))
        trial.arm()
        result=trial.decision(0)
        self.assertEqual(result['boundary'],0x200605e4)
        self.assertEqual(trial.live()[:2],(0,0))
        before=trial._registers()
        trial.uc.emu_start(0x200605e4,0x200605e8,count=100,timeout=1000000)
        self.assertEqual(trial.uc.reg_read(trial.a.UC_ARM_REG_PC),0x200605e8)
        self.assertEqual(trial._registers(),before)
        self.assertEqual(trial.uc.reg_read(trial.a.UC_ARM_REG_SP),STACK+0xeff8)
        self.assertEqual(bytes(trial.uc.mem_read(STACK+0xeff8,8)),struct.pack('<2I',before[4],combined.RETURN))
        self.assertEqual(struct.unpack('<4I',trial.uc.mem_read(combined.EPOCH,16)),(8,2,0,0))
        self.assertEqual(struct.unpack_from('<2I',trial.storage()),(1,0))

    def test_nonstandard_copy_lengths_keep_original_memcpy(self):
        baseline,trial=combined.CombinedTrial(self.app,False),combined.CombinedTrial(self.app)
        for length in (0,1,2,3,4,215):
            results=[]
            for t in (baseline,trial):
                self.reset(t,status=2,count=512)
                t.uc.mem_write(combined.SCRATCH,bytes(range(216)))
                t.uc.mem_write(combined.RING,b'\xa5'*220)
                t.h.run(0x20066f80,(combined.RING,combined.SCRATCH,length),stop=0x20066f84,budget=2000)
                results.append(bytes(t.uc.mem_read(combined.RING,220)))
                self.assertEqual(t.control(),(0,0))
            self.assertEqual(results[0],results[1])

    def test_inactive_carrier_matches_original_publisher_and_edits_are_disjoint(self):
        baseline,trial=combined.CombinedTrial(self.app,False),combined.CombinedTrial(self.app)
        for status,control in ((0,(0,0)),(1,(0,0)),(2,(598,2)),(3,(0,0)),(4,(0,0)),(5,(0,3)),(6,(0,3))):
            for index in (0,1913):
                for enabled in (0,1):
                    rows=[]
                    for t in (baseline,trial):
                        self.reset(t,status=status,control=control)
                        rows.append(t.publish(index,enabled=enabled))
                    for key in ('ring','index_after','fill_after'): self.assertEqual(rows[0][key],rows[1][key])
                    self.assertEqual(trial.storage(),baseline.storage())
                    self.assertEqual(trial.control(),control)
        edits=combined.offline_edits(self.app)
        self.assertEqual(len(edits),17)
        spans=sorted((a,a+len(data)) for a,data in edits)
        self.assertTrue(all(a[1]<=b[0] for a,b in zip(spans,spans[1:])))
        expected_sites={a for a,_ in combined.hooks.SITES.values()}|{a for a,_ in combined.epoch.SITES.values()}|{a for a,_ in combined.RECORDER_SITES.values()}
        self.assertEqual({a for a,data in edits if a<combined.CODE},expected_sites)


if __name__=='__main__': unittest.main()
