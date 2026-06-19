// Post-analysis JSON dump for the SDS100 SUB MCU firmware.
//
// Run via Ghidra's headless analyzer with -postScript after auto-analysis
// has completed. Produces Metacache/Dev/RE/firmware/analysis_dump.json containing:
//
//   metadata          - Ghidra version, base addr, payload SHA-256, timestamp
//   strings[]         - every defined string with addr, value, length, xrefs
//   format_strings[]  - subset whose value matches %[0-9.]*[diouxXfsc%]
//                       with the function each xref lives in
//   functions[]       - addr, name, size, callers, callees, decompiled C
//                       (truncated to ~4000 chars for size discipline)
//   peripheral_users  - LPC43xx peripheral -> [function addrs that touch it]
//   dispatch_candidates[] - functions that reference >=3 short ASCII strings
//                           heuristically grouped as command mnemonics
//
// Idempotent. Output overwrites previous analysis_dump.json.
//
//@category SDS100
//@author scanner-manager auto-RE
//@runtime Java

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.framework.Application;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressRange;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.SymbolTable;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileInputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class DumpAnalysis extends GhidraScript {

    /** Cap on per-function decompile output to keep total dump size sane. */
    private static final int DECOMP_CHAR_CAP = 4000;
    private static final int DECOMP_TIMEOUT_S = 30;

    /** Regex that flags a string as a printf-style format string. */
    private static final Pattern FORMAT_RE = Pattern.compile("%[-+ #0]*[0-9]*(?:\\.[0-9]+)?[lhLzj]*[diouxXeEfgGsc%]");

    /** Heuristic min-references for dispatch candidate. */
    private static final int DISPATCH_MIN_STRINGS = 3;
    private static final int DISPATCH_MAX_STRING_LEN = 6;

    /**
     * LPC43xx peripheral block layout. Each entry: {name, base, span}.
     * Address-range matching uses base..base+span-1.
     */
    private static final Object[][] PERIPHERALS = {
        {"USART0",     0x40081000L, 0x1000L},
        {"USART1",     0x40082000L, 0x1000L},
        {"SSP0",       0x40083000L, 0x1000L},
        {"TIMER0",     0x40084000L, 0x1000L},
        {"TIMER1",     0x40085000L, 0x1000L},
        {"SCU",        0x40086000L, 0x1000L},
        {"GPIO_INT",   0x40087000L, 0x1000L},
        {"USART2",     0x400C1000L, 0x1000L},
        {"USART3",     0x400C2000L, 0x1000L},
        {"TIMER2",     0x400C3000L, 0x1000L},
        {"TIMER3",     0x400C4000L, 0x1000L},
        {"SSP1",       0x400C5000L, 0x1000L},
        {"I2C0",       0x400A1000L, 0x1000L},
        {"I2C1",       0x400E0000L, 0x1000L},
        {"ADC0",       0x400E3000L, 0x1000L},
        {"ADC1",       0x400E4000L, 0x1000L},
        {"USB0",       0x40006000L, 0x1000L},
        {"USB1",       0x40007000L, 0x1000L},
        {"DMA",        0x40002000L, 0x1000L},
        {"GPIO_PORTS", 0x400F4000L, 0x4000L},
        {"SPI",        0x40100000L, 0x1000L},
        {"NVIC",       0xE000E000L, 0x2000L},
    };

    @Override
    protected void run() throws Exception {
        long t0 = System.currentTimeMillis();
        println("[DumpAnalysis] Begin: program=" + currentProgram.getName());

        Path repoRoot = resolveRepoRoot();
        Path outPath = repoRoot.resolve("Metacache/Dev/RE/firmware/analysis_dump.json");
        Files.createDirectories(outPath.getParent());

        DecompInterface decomp = new DecompInterface();
        DecompileOptions options = new DecompileOptions();
        decomp.setOptions(options);
        decomp.openProgram(currentProgram);
        try {
            try (BufferedWriter bw = new BufferedWriter(new OutputStreamWriter(
                    Files.newOutputStream(outPath), StandardCharsets.UTF_8))) {
                JsonWriter w = new JsonWriter(bw);
                w.beginObject();
                writeMetadata(w, repoRoot);
                StringScan strings = scanStrings();
                writeStringsSection(w, "strings", strings.all);
                writeStringsSection(w, "format_strings", strings.formats);
                writeFunctions(w, decomp);
                writeStringsByFunction(w, strings.byFunction);
                writePeripheralUsers(w);
                writeDispatchCandidates(w, strings.byFunction);
                w.endObject();
            }
        } finally {
            decomp.dispose();
        }

        long size = Files.size(outPath);
        long elapsedMs = System.currentTimeMillis() - t0;
        println(String.format(
            "[DumpAnalysis] Wrote %s (%.2f MB) in %.1fs",
            outPath, size / 1048576.0, elapsedMs / 1000.0));
    }

    // ---------------------------------------------------------------------
    //  Sections
    // ---------------------------------------------------------------------

    private void writeMetadata(JsonWriter w, Path repoRoot) throws Exception {
        w.key("metadata").beginObject();
        w.kv("ghidra_version", Application.getApplicationVersion());
        w.kv("program_name", currentProgram.getName());
        w.kv("language", currentProgram.getLanguageID().toString());
        w.kv("compiler_spec", currentProgram.getCompilerSpec().getCompilerSpecID().toString());
        w.kv("image_base", currentProgram.getImageBase().toString());
        w.kv("min_address", currentProgram.getMinAddress().toString());
        w.kv("max_address", currentProgram.getMaxAddress().toString());
        w.kv("timestamp_utc", Instant.now().toString());
        w.kv("repo_root", repoRoot.toString());
        // SHA-256 of the original binary, if findable.
        Path firmware = repoRoot.resolve("Metacache/Dev/RE/firmware/sub_1.03.15_inflated.bin");
        if (firmware.toFile().exists()) {
            w.kv("payload_sha256", sha256(firmware.toFile()));
            w.kv("payload_size", String.valueOf(firmware.toFile().length()));
        }
        w.endObject();
    }

    private static class StringRec {
        String addr;
        String value;
        int length;
        boolean isFormat;
        List<String> xrefAddrs = new ArrayList<>();
        List<String> xrefFunctions = new ArrayList<>();
    }

    private static class StringScan {
        List<StringRec> all = new ArrayList<>();
        List<StringRec> formats = new ArrayList<>();
        // function-addr (hex string) -> list of strings the function references
        Map<String, List<StringRec>> byFunction = new HashMap<>();
    }

    private StringScan scanStrings() {
        StringScan out = new StringScan();
        ReferenceManager rm = currentProgram.getReferenceManager();
        DataIterator it = currentProgram.getListing().getDefinedData(true);
        int count = 0;
        while (it.hasNext() && !monitor.isCancelled()) {
            Data d = it.next();
            String typeName = d.getDataType().getName().toLowerCase();
            // Only keep ASCII / unicode string types.
            if (!typeName.contains("string") && !typeName.equals("char") && !typeName.contains("char[")) {
                continue;
            }
            Object val = d.getValue();
            if (!(val instanceof String)) continue;
            String s = (String) val;
            if (s.isEmpty()) continue;

            StringRec r = new StringRec();
            r.addr = d.getAddress().toString();
            r.value = s;
            r.length = s.length();
            r.isFormat = FORMAT_RE.matcher(s).find();

            ReferenceIterator refs = rm.getReferencesTo(d.getAddress());
            while (refs.hasNext()) {
                Reference ref = refs.next();
                Address from = ref.getFromAddress();
                r.xrefAddrs.add(from.toString());
                Function f = currentProgram.getFunctionManager().getFunctionContaining(from);
                if (f != null) {
                    r.xrefFunctions.add(f.getEntryPoint().toString());
                    out.byFunction.computeIfAbsent(f.getEntryPoint().toString(),
                                                  k -> new ArrayList<>()).add(r);
                }
            }
            out.all.add(r);
            if (r.isFormat) out.formats.add(r);
            count++;
            if ((count % 500) == 0) {
                monitor.setMessage("Strings scanned: " + count);
            }
        }
        println("[DumpAnalysis] strings=" + out.all.size() + " format=" + out.formats.size());
        return out;
    }

    private void writeStringsSection(JsonWriter w, String key, List<StringRec> recs) throws Exception {
        w.key(key).beginArray();
        for (StringRec r : recs) {
            w.beginObject();
            w.kv("addr", r.addr);
            w.kv("value", r.value);
            w.kvNum("length", r.length);
            if (r.isFormat) w.kvBool("is_format", true);
            w.key("xrefs_from").beginArray();
            for (String a : r.xrefAddrs) w.value(a);
            w.endArray();
            w.key("xref_functions").beginArray();
            for (String f : r.xrefFunctions) w.value(f);
            w.endArray();
            w.endObject();
        }
        w.endArray();
    }

    private void writeStringsByFunction(JsonWriter w, Map<String, List<StringRec>> byFunc) throws Exception {
        w.key("strings_by_function").beginObject();
        // Stable order
        Map<String, List<StringRec>> sorted = new TreeMap<>(byFunc);
        for (Map.Entry<String, List<StringRec>> e : sorted.entrySet()) {
            w.key(e.getKey()).beginArray();
            for (StringRec r : e.getValue()) {
                w.beginObject();
                w.kv("addr", r.addr);
                w.kv("value", r.value);
                w.endObject();
            }
            w.endArray();
        }
        w.endObject();
    }

    private void writeFunctions(JsonWriter w, DecompInterface decomp) throws Exception {
        w.key("functions").beginArray();
        FunctionIterator fi = currentProgram.getFunctionManager().getFunctions(true);
        int count = 0;
        while (fi.hasNext() && !monitor.isCancelled()) {
            Function f = fi.next();
            count++;
            if ((count % 100) == 0) monitor.setMessage("Functions emitted: " + count);

            w.beginObject();
            w.kv("addr", f.getEntryPoint().toString());
            w.kv("name", f.getName());
            w.kvNum("size", (int) f.getBody().getNumAddresses());

            // Callers
            w.key("callers").beginArray();
            for (Function caller : f.getCallingFunctions(monitor)) {
                w.value(caller.getEntryPoint().toString());
            }
            w.endArray();

            // Callees
            w.key("callees").beginArray();
            for (Function callee : f.getCalledFunctions(monitor)) {
                w.value(callee.getEntryPoint().toString());
            }
            w.endArray();

            // Peripheral accesses
            List<String> pHits = peripheralAccesses(f);
            w.key("peripheral_accesses").beginArray();
            for (String p : pHits) w.value(p);
            w.endArray();

            // Decompile - cap at DECOMP_CHAR_CAP
            try {
                DecompileResults res = decomp.decompileFunction(f, DECOMP_TIMEOUT_S, monitor);
                if (res != null && res.getDecompiledFunction() != null) {
                    String c = res.getDecompiledFunction().getC();
                    if (c != null) {
                        if (c.length() > DECOMP_CHAR_CAP) {
                            c = c.substring(0, DECOMP_CHAR_CAP) + "\n/* ... truncated by DumpAnalysis ... */";
                        }
                        w.kv("decompile", c);
                    }
                }
            } catch (Exception e) {
                w.kv("decompile_error", e.getMessage());
            }

            w.endObject();
        }
        w.endArray();
        println("[DumpAnalysis] functions=" + count);
    }

    private List<String> peripheralAccesses(Function f) {
        List<String> hits = new ArrayList<>();
        InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
        java.util.Set<String> seen = new java.util.HashSet<>();
        while (it.hasNext()) {
            Instruction insn = it.next();
            for (Reference ref : insn.getReferencesFrom()) {
                Address to = ref.getToAddress();
                if (to == null) continue;
                long val = to.getOffset();
                String name = peripheralForAddress(val);
                if (name != null && !seen.contains(name)) {
                    seen.add(name);
                    hits.add(name);
                }
            }
        }
        Collections.sort(hits);
        return hits;
    }

    private static String peripheralForAddress(long addr) {
        for (Object[] row : PERIPHERALS) {
            long base = (Long) row[1];
            long span = (Long) row[2];
            if (addr >= base && addr < base + span) {
                return (String) row[0];
            }
        }
        return null;
    }

    private void writePeripheralUsers(JsonWriter w) throws Exception {
        Map<String, List<String>> users = new LinkedHashMap<>();
        for (Object[] row : PERIPHERALS) {
            users.put((String) row[0], new ArrayList<>());
        }
        FunctionIterator fi = currentProgram.getFunctionManager().getFunctions(true);
        while (fi.hasNext() && !monitor.isCancelled()) {
            Function f = fi.next();
            for (String name : peripheralAccesses(f)) {
                users.get(name).add(f.getEntryPoint().toString());
            }
        }
        w.key("peripheral_users").beginObject();
        for (Map.Entry<String, List<String>> e : users.entrySet()) {
            if (e.getValue().isEmpty()) continue;
            w.key(e.getKey()).beginArray();
            for (String addr : e.getValue()) w.value(addr);
            w.endArray();
        }
        w.endObject();
    }

    private void writeDispatchCandidates(JsonWriter w, Map<String, List<StringRec>> byFunc) throws Exception {
        w.key("dispatch_candidates").beginArray();
        for (Map.Entry<String, List<StringRec>> e : byFunc.entrySet()) {
            List<StringRec> all = e.getValue();
            // De-dupe per function (a string may appear twice if used twice).
            java.util.LinkedHashMap<String, StringRec> uniq = new java.util.LinkedHashMap<>();
            for (StringRec r : all) {
                if (r.length > DISPATCH_MAX_STRING_LEN) continue;
                if (r.isFormat) continue;
                if (!isPrintableMnemonic(r.value)) continue;
                uniq.putIfAbsent(r.value, r);
            }
            if (uniq.size() < DISPATCH_MIN_STRINGS) continue;
            Function f = currentProgram.getFunctionManager().getFunctionAt(toAddr(Long.parseLong(e.getKey().replace("0x", ""), 16)));
            w.beginObject();
            w.kv("function", e.getKey());
            if (f != null) w.kv("function_name", f.getName());
            w.kvNum("mnemonic_count", uniq.size());
            w.key("mnemonics").beginArray();
            for (StringRec r : uniq.values()) {
                w.beginObject();
                w.kv("value", r.value);
                w.kv("string_addr", r.addr);
                w.endObject();
            }
            w.endArray();
            w.endObject();
        }
        w.endArray();
    }

    private static boolean isPrintableMnemonic(String s) {
        if (s == null || s.isEmpty()) return false;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c < 0x20 || c > 0x7E) return false;
        }
        return true;
    }

    // ---------------------------------------------------------------------
    //  Helpers
    // ---------------------------------------------------------------------

    private static Path resolveRepoRoot() {
        String env = System.getenv("REPO_ROOT");
        if (env != null && !env.isEmpty()) return Paths.get(env);
        // Heuristic: walk up from cwd until we find an "Metacache/Dev/RE" directory.
        Path cur = Paths.get(System.getProperty("user.dir"));
        for (int i = 0; i < 6 && cur != null; i++) {
            if (cur.resolve("Metacache/Dev/RE").toFile().isDirectory()) return cur;
            cur = cur.getParent();
        }
        // Fallback: assume cwd.
        return Paths.get(System.getProperty("user.dir"));
    }

    private static String sha256(File f) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        try (FileInputStream in = new FileInputStream(f)) {
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) md.update(buf, 0, n);
        }
        byte[] dig = md.digest();
        StringBuilder sb = new StringBuilder(dig.length * 2);
        for (byte b : dig) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    // ---------------------------------------------------------------------
    //  Streaming JSON writer (no external dependency).
    // ---------------------------------------------------------------------

    private static final class JsonWriter {
        private final BufferedWriter bw;
        private final java.util.Deque<Boolean> needComma = new java.util.ArrayDeque<>();
        private boolean keyWritten = false;

        JsonWriter(BufferedWriter bw) { this.bw = bw; }

        JsonWriter beginObject() throws Exception { writeSep(); bw.write('{'); needComma.push(false); return this; }
        JsonWriter endObject()   throws Exception { needComma.pop(); bw.write('}'); markComma(); return this; }
        JsonWriter beginArray()  throws Exception { writeSep(); bw.write('['); needComma.push(false); return this; }
        JsonWriter endArray()    throws Exception { needComma.pop(); bw.write(']'); markComma(); return this; }

        JsonWriter key(String k) throws Exception {
            if (!needComma.isEmpty() && needComma.peek()) bw.write(',');
            if (!needComma.isEmpty()) needComma.pop(); needComma.push(true);
            bw.write(quote(k));
            bw.write(':');
            keyWritten = true;
            return this;
        }
        JsonWriter value(String s) throws Exception {
            writeSep();
            bw.write(quote(s));
            keyWritten = false;
            return this;
        }
        JsonWriter kv(String k, String v) throws Exception {
            key(k);
            if (v == null) bw.write("null"); else bw.write(quote(v));
            keyWritten = false;
            return this;
        }
        JsonWriter kvNum(String k, long v) throws Exception {
            key(k);
            bw.write(Long.toString(v));
            keyWritten = false;
            return this;
        }
        JsonWriter kvBool(String k, boolean v) throws Exception {
            key(k);
            bw.write(v ? "true" : "false");
            keyWritten = false;
            return this;
        }

        private void writeSep() throws Exception {
            if (keyWritten) {
                keyWritten = false;
                return;
            }
            if (!needComma.isEmpty() && needComma.peek()) bw.write(',');
            if (!needComma.isEmpty()) { needComma.pop(); needComma.push(true); }
        }
        private void markComma() {
            if (!needComma.isEmpty()) { needComma.pop(); needComma.push(true); }
        }

        private static String quote(String s) {
            StringBuilder sb = new StringBuilder(s.length() + 2);
            sb.append('"');
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                switch (c) {
                    case '"':  sb.append("\\\""); break;
                    case '\\': sb.append("\\\\"); break;
                    case '\b': sb.append("\\b"); break;
                    case '\f': sb.append("\\f"); break;
                    case '\n': sb.append("\\n"); break;
                    case '\r': sb.append("\\r"); break;
                    case '\t': sb.append("\\t"); break;
                    default:
                        if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                        else sb.append(c);
                }
            }
            sb.append('"');
            return sb.toString();
        }
    }
}
