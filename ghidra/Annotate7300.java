// Import application.decoded.bin as ARM:LE:32:v7 at 0x20005000, then run.
// @category IC7300
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.symbol.SourceType;

public class Annotate7300 extends GhidraScript {
    public void run() throws Exception {
        Address base = toAddr(0x20005000L);
        if (currentProgram.getMemory().getInt(base) != 0xe59ff018)
            throw new IllegalArgumentException("Wrong image or load address");
        createLabel(base, "application_vectors", true);
        for (int v=0; v<8; v++) {
            Address slot=base.add(v*4);
            disassemble(slot);
            long target=Integer.toUnsignedLong(currentProgram.getMemory().getInt(base.add(0x20+v*4)));
            Address handler=toAddr(target);
            createLabel(handler, "exception_handler_"+v, true);
            disassemble(handler);
        }
        setPlateComment(base,"IC-7300 v1.42 main application; loader destination verified at RAM 0x20005000. See research/address-map.json for candidate xrefs, not confirmed APIs.");
        println("Annotated vector targets; run Auto Analyze and inspect candidate xrefs manually.");
    }
}
