// Pre-analysis setup for the SDS100 SUB MCU firmware.
//
// Run via Ghidra's headless analyzer with -preScript:
//   analyzeHeadless.bat <projDir> SDS100_SUB \
//       -import sub_1.03.15_inflated.bin \
//       -loader BinaryLoader -loader-baseAddr 0x14000000 \
//       -processor "ARM:LE:32:Cortex" \
//       -preScript SetupSubProject.java \
//       -postScript DumpAnalysis.java \
//       -scriptPath <this-folder>
//
// Responsibilities:
//   1. Add 5 uninitialized memory blocks for SRAM / peripherals / NVIC.
//   2. Parse LPC43xx.svd (via the SVD_PATH env var or default location)
//      and add a named label at every peripheral register address so
//      Ghidra cross-references resolve cleanly to e.g. "USART1_DLL".
//   3. Set the Thumb bit at 0x140001D4 and add it as an entry point
//      (so the auto-analysis pass that follows starts in Thumb mode).
//   4. Disassemble from 0x140001D4.
//
// Idempotent: re-running over an already-prepared program is safe; we
// skip any block whose start address is already covered.
//
//@category SDS100
//@author scanner-manager auto-RE
//@runtime Java

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.script.GhidraScript;
import ghidra.framework.options.Options;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.StringDataType;
import ghidra.program.model.lang.Register;
import ghidra.program.model.lang.RegisterValue;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.listing.Program;
import ghidra.program.model.listing.ProgramContext;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.SymbolTable;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import java.io.File;
import java.math.BigInteger;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

public class SetupSubProject extends GhidraScript {

    private static final long ENTRY_VMA = 0x140001D4L;

    /** Memory blocks we always create (one row per row in the runbook). */
    private static final long[][] BLOCKS = {
        // start, length
        {0x10000000L, 0x20000L},   // sram_loc0
        {0x10080000L, 0x12000L},   // sram_loc1
        {0x20000000L, 0x10000L},   // sram_ahb
        {0x40000000L, 0x100000L},  // peripherals
        {0xE0000000L, 0x100000L},  // nvic
    };
    private static final String[] BLOCK_NAMES = {
        "sram_loc0", "sram_loc1", "sram_ahb", "peripherals", "nvic",
    };
    private static final boolean[] BLOCK_EXEC      = {true,  true,  false, false, false};
    private static final boolean[] BLOCK_VOLATILE  = {false, false, false, true,  true };

    @Override
    protected void run() throws Exception {
        println("[SetupSubProject] Begin: program=" + currentProgram.getName());

        addSupportBlocks();
        addPeripheralLabelsFromSvd();
        configureAnalysisOptions();
        setThumbEntry();
        scanForShortMnemonics();

        println("[SetupSubProject] Done.");
    }

    /** Lower the ASCII string analyzer's minimum length so 3-char command
     *  mnemonics like MDL/VER/STS get auto-detected. */
    private void configureAnalysisOptions() {
        try {
            Options opts = currentProgram.getOptions(Program.ANALYSIS_PROPERTIES);
            // Try a few known names across Ghidra versions.
            String[] keys = {
                "ASCII Strings.Minimum String Length",
                "ASCII Strings.Min String Length",
            };
            boolean set = false;
            for (String k : keys) {
                try {
                    opts.setInt(k, 3);
                    println("[SetupSubProject] " + k + " = 3");
                    set = true;
                    break;
                } catch (Exception ignored) {
                }
            }
            if (!set) {
                println("[SetupSubProject] WARN: could not lower ASCII Strings minimum (option name varies).");
            }
            try {
                opts.setBoolean("ASCII Strings.Search Only in Initialized Memory", true);
            } catch (Exception ignored) {
            }
        } catch (Exception e) {
            println("[SetupSubProject] WARN: configureAnalysisOptions failed: " + e.getMessage());
        }
    }

    /** Walk the read-only payload and create short-string data at any
     *  run of 2..6 printable ASCII bytes followed by a NUL.
     *
     *  EMPIRICAL FINDING (Session 7): the SDS100 SUB firmware does NOT
     *  have a string-table dispatch.  It uses per-character compares
     *  (e.g. {@code if (in[0]=='M' && in[1]=='D' && in[2]=='L')}), so
     *  literal mnemonics like "MDL" do not exist as defined strings.
     *  We still run this scan because it'll catch any future firmware
     *  that uses a more conventional dispatch style.
     */
    private void scanForShortMnemonics() {
        Memory mem = currentProgram.getMemory();
        Listing listing = currentProgram.getListing();
        long startVma = 0x14000000L;
        long endVma   = startVma + 0x16080L;
        int created = 0;
        long off = startVma;
        try {
            while (off < endVma - 1) {
                Address a = toAddr(off);
                if (!mem.contains(a)) break;
                int b = mem.getByte(a) & 0xFF;
                if (!isMnemonicChar(b)) {
                    off++;
                    continue;
                }
                int len = 1;
                while (off + len < endVma) {
                    Address aLen = toAddr(off + len);
                    if (!mem.contains(aLen)) break;
                    int b2 = mem.getByte(aLen) & 0xFF;
                    if (!isMnemonicChar(b2)) break;
                    len++;
                }
                if (len >= 2 && len <= 6 && (off + len) < endVma) {
                    Address aTerm = toAddr(off + len);
                    if (mem.contains(aTerm) && (mem.getByte(aTerm) & 0xFF) == 0x00) {
                        if (listing.getDataAt(a) == null && listing.getInstructionAt(a) == null) {
                            try {
                                listing.createData(a, StringDataType.dataType, len + 1);
                                created++;
                            } catch (Exception ignored) {
                            }
                        }
                    }
                }
                off += Math.max(1, len + 1);
            }
        } catch (Exception e) {
            println("[SetupSubProject] WARN: short-mnemonic scan: " + e.getMessage());
        }
        println(String.format("[SetupSubProject] + %d short-mnemonic strings (heuristic)", created));
    }

    private static boolean isMnemonicChar(int b) {
        return (b >= 'A' && b <= 'Z') || (b >= 'a' && b <= 'z') || (b >= '0' && b <= '9')
                || b == '_';
    }

    private void addSupportBlocks() throws Exception {
        Memory memory = currentProgram.getMemory();
        for (int i = 0; i < BLOCKS.length; i++) {
            String name = BLOCK_NAMES[i];
            long startVma = BLOCKS[i][0];
            long length   = BLOCKS[i][1];
            Address start = toAddr(startVma);

            // Skip if a block already covers this start (idempotency / re-runs).
            MemoryBlock existing = memory.getBlock(start);
            if (existing != null) {
                println(String.format(
                    "[SetupSubProject] block at 0x%08X already exists (%s); skipping",
                    startVma, existing.getName()));
                continue;
            }

            MemoryBlock block = memory.createUninitializedBlock(name, start, length, false);
            block.setRead(true);
            block.setWrite(true);
            block.setExecute(BLOCK_EXEC[i]);
            block.setVolatile(BLOCK_VOLATILE[i]);
            println(String.format(
                "[SetupSubProject] + %s: 0x%08X..0x%08X (vol=%s, exec=%s)",
                name, startVma, startVma + length - 1,
                BLOCK_VOLATILE[i], BLOCK_EXEC[i]));
        }
    }

    private void addPeripheralLabelsFromSvd() {
        Path svdPath = resolveSvdPath();
        if (svdPath == null || !svdPath.toFile().exists()) {
            println("[SetupSubProject] WARN: LPC43xx.svd not found; no peripheral labels added.");
            println("[SetupSubProject]       (looked for SVD_PATH env var, then a few defaults.)");
            return;
        }
        try {
            int created = parseAndLabel(svdPath.toFile());
            println(String.format("[SetupSubProject] + %d peripheral register labels from %s",
                                  created, svdPath));
        } catch (Exception e) {
            println("[SetupSubProject] WARN: SVD parse failed: " + e.getMessage());
        }
    }

    private Path resolveSvdPath() {
        String env = System.getenv("SVD_PATH");
        if (env != null && !env.isEmpty()) {
            return Paths.get(env);
        }
        // Default: <project root>/AI/Dev/RE/firmware/LPC43xx.svd
        // We don't know the project root from the script; try a few sensible spots.
        Path[] candidates = new Path[] {
            Paths.get(System.getProperty("user.dir"), "AI", "Dev", "RE", "firmware", "LPC43xx.svd"),
            Paths.get(System.getProperty("user.dir"), "..", "AI", "Dev", "RE", "firmware", "LPC43xx.svd"),
        };
        for (Path p : candidates) {
            if (p.toFile().exists()) {
                return p;
            }
        }
        return null;
    }

    private int parseAndLabel(File svdFile) throws Exception {
        DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
        dbf.setNamespaceAware(false);
        dbf.setValidating(false);
        // Disable DTD/external loading - SVD files are self-contained.
        dbf.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false);
        dbf.setFeature("http://xml.org/sax/features/external-general-entities", false);
        dbf.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
        DocumentBuilder db = dbf.newDocumentBuilder();
        Document doc = db.parse(svdFile);

        SymbolTable st = currentProgram.getSymbolTable();
        NodeList peripherals = doc.getElementsByTagName("peripheral");
        int created = 0;

        // Cache for `derivedFrom`: peripheralName -> { registerName -> offset }.
        java.util.Map<String, Long> peripheralBaseByName = new java.util.HashMap<>();
        java.util.Map<String, NodeList> registersByName  = new java.util.HashMap<>();

        // First pass: collect base addresses for inheritance.
        for (int i = 0; i < peripherals.getLength(); i++) {
            Element p = (Element) peripherals.item(i);
            String name = textOf(p, "name");
            String baseStr = textOf(p, "baseAddress");
            if (name == null || baseStr == null) continue;
            try {
                peripheralBaseByName.put(name, parseSvdNumber(baseStr));
            } catch (NumberFormatException ignored) {
                // skip
            }
            NodeList regs = p.getElementsByTagName("register");
            if (regs.getLength() > 0) {
                registersByName.put(name, regs);
            }
        }

        // Second pass: emit labels.
        for (int i = 0; i < peripherals.getLength(); i++) {
            Element p = (Element) peripherals.item(i);
            String name = textOf(p, "name");
            if (name == null) continue;
            Long base = peripheralBaseByName.get(name);
            if (base == null) continue;

            // Resolve registers; allow `derivedFrom` reference to inherit.
            NodeList regs = registersByName.get(name);
            String derivedFrom = p.getAttribute("derivedFrom");
            if ((regs == null || regs.getLength() == 0) && derivedFrom != null && !derivedFrom.isEmpty()) {
                regs = registersByName.get(derivedFrom);
            }
            if (regs == null) continue;

            for (int r = 0; r < regs.getLength(); r++) {
                Element reg = (Element) regs.item(r);
                String regName = textOf(reg, "name");
                String offsetStr = textOf(reg, "addressOffset");
                if (regName == null || offsetStr == null) continue;
                long offset;
                try {
                    offset = parseSvdNumber(offsetStr);
                } catch (NumberFormatException e) {
                    continue;
                }
                Address addr;
                try {
                    addr = toAddr(base + offset);
                } catch (Exception e) {
                    continue;
                }
                String label = (name + "_" + regName).replaceAll("[^A-Za-z0-9_]", "_");
                try {
                    st.createLabel(addr, label, SourceType.IMPORTED);
                    created++;
                } catch (Exception e) {
                    // duplicate label; ignore
                }
            }
        }
        return created;
    }

    private static String textOf(Element parent, String tag) {
        NodeList nl = parent.getElementsByTagName(tag);
        if (nl.getLength() == 0) return null;
        // First direct child is enough; SVD has at most one <name>/<baseAddress>.
        Node n = nl.item(0);
        if (n.getParentNode() != parent) {
            // descendant; still use text content
        }
        String t = n.getTextContent();
        return (t == null) ? null : t.trim();
    }

    private static long parseSvdNumber(String s) {
        s = s.trim();
        if (s.startsWith("0x") || s.startsWith("0X")) {
            return Long.parseLong(s.substring(2), 16);
        }
        if (s.endsWith("k") || s.endsWith("K")) {
            return Long.parseLong(s.substring(0, s.length() - 1)) * 1024L;
        }
        return Long.parseLong(s);
    }

    private void setThumbEntry() throws Exception {
        Address entry = toAddr(ENTRY_VMA);
        ProgramContext ctx = currentProgram.getProgramContext();
        Register tmode = ctx.getRegister("TMode");
        if (tmode != null) {
            RegisterValue v = new RegisterValue(tmode, BigInteger.ONE);
            ctx.setRegisterValue(entry, entry, v);
            println(String.format(
                "[SetupSubProject] TMode=1 set at 0x%08X (Thumb)", ENTRY_VMA));
        } else {
            println("[SetupSubProject] WARN: register 'TMode' not found - is processor ARM:LE:32:Cortex?");
        }

        currentProgram.getSymbolTable().addExternalEntryPoint(entry);
        try {
            currentProgram.getSymbolTable().createLabel(entry, "_reset_entry", SourceType.IMPORTED);
        } catch (Exception ignored) {
        }

        DisassembleCommand cmd = new DisassembleCommand(entry, null, true);
        cmd.applyTo(currentProgram, monitor);
        println(String.format(
            "[SetupSubProject] disassembled from 0x%08X (entry point)", ENTRY_VMA));
    }
}
