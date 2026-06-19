// Targeted decompile dumper for SDS100 SUB MCU firmware.
//
// Run via Ghidra's headless analyzer with -postScript on an already-analyzed
// project. Reads a comma-separated list of function addresses (or names)
// from the DECOMPILE_TARGETS environment variable and emits, per target:
//
//   Metacache/Dev/RE/firmware/decompiles/<addr>_<name>.json
//
// Each per-function JSON contains:
//   addr, name, size, body_min, body_max
//   callers[]  - {addr, name}
//   callees[]  - {addr, name}
//   peripheral_accesses[] - LPC43xx peripheral names this function touches
//   string_xrefs[] - strings referenced from this function (with format hint)
//   decompile  - FULL C output (no truncation, unlike DumpAnalysis.java)
//
// Idempotent. Safe to re-run after reanalysis.
//
//@category SDS100
//@author scanner-manager auto-RE
//@runtime Java

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressRange;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.SymbolTable;

import java.io.BufferedWriter;
import java.io.File;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

public class DecompileFunctions extends GhidraScript {

    private static final int DECOMP_TIMEOUT_S = 60;
    private static final Pattern FORMAT_RE = Pattern.compile(
        "%[-+ #0]*[0-9]*(?:\\.[0-9]+)?[lhLzj]*[diouxXeEfgGsc%]");

    /** LPC43xx peripheral layout - mirrors DumpAnalysis.java. */
    private static final Object[][] PERIPHERALS = {
        {"USART0",     0x40081000L, 0x1000L},
        {"USART1",     0x40082000L, 0x1000L},
        {"USART2",     0x400C1000L, 0x1000L},
        {"USART3",     0x400C2000L, 0x1000L},
        {"SSP0",       0x40083000L, 0x1000L},
        {"SSP1",       0x400C5000L, 0x1000L},
        {"I2C0",       0x400A1000L, 0x1000L},
        {"I2C1",       0x400E0000L, 0x1000L},
        {"USB0",       0x40006000L, 0x1000L},
        {"USB1",       0x40007000L, 0x1000L},
        {"GPIO",       0x400F4000L, 0x4000L},
        {"SCU",        0x40086000L, 0x1000L},
        {"NVIC",       0xE000E000L, 0x1000L},
        {"TIMER0",     0x40084000L, 0x1000L},
        {"TIMER1",     0x40085000L, 0x1000L},
        {"TIMER2",     0x400C3000L, 0x1000L},
        {"TIMER3",     0x400C4000L, 0x1000L},
        {"SDMMC",      0x40004000L, 0x1000L},
        {"DMA",        0x40002000L, 0x1000L},
        {"CGU",        0x40050000L, 0x1000L},
        {"CCU1",       0x40051000L, 0x1000L},
        {"CCU2",       0x40052000L, 0x1000L},
        {"RGU",        0x40053000L, 0x1000L},
        {"PMC",        0x40042000L, 0x1000L},
    };

    @Override
    public void run() throws Exception {
        String targetSpec = System.getenv("DECOMPILE_TARGETS");
        if (targetSpec == null || targetSpec.trim().isEmpty()) {
            // Fallback: a sensible default set covering Round 1+2 entry points.
            targetSpec = "0x14010554,0x1400e57c,0x1400eb24,0x1400e900,0x14010fec";
            println("[DecompileFunctions] DECOMPILE_TARGETS not set; using defaults: " + targetSpec);
        } else {
            println("[DecompileFunctions] DECOMPILE_TARGETS=" + targetSpec);
        }

        Path outDir = Paths.get(System.getenv().getOrDefault(
            "DECOMPILE_OUTDIR",
            "Metacache/Dev/RE/firmware/decompiles"));
        Files.createDirectories(outDir);
        println("[DecompileFunctions] outDir=" + outDir.toAbsolutePath());

        List<String> targets = new ArrayList<>();
        for (String t : targetSpec.split(",")) {
            String s = t.trim();
            if (!s.isEmpty()) targets.add(s);
        }

        DecompInterface decomp = new DecompInterface();
        DecompileOptions opts = new DecompileOptions();
        decomp.setOptions(opts);
        decomp.openProgram(currentProgram);

        int ok = 0, fail = 0;
        for (String t : targets) {
            try {
                Function f = resolveFunction(t);
                if (f == null) {
                    println("[!] Cannot resolve target: " + t);
                    fail++;
                    continue;
                }
                String name = f.getName();
                String addr = f.getEntryPoint().toString();
                String fileBase = String.format("%s_%s",
                    addr.replaceFirst("^0x", ""),
                    name.replaceAll("[^A-Za-z0-9_.]", "_"));
                Path outFile = outDir.resolve(fileBase + ".json");

                writeOne(decomp, f, outFile);
                println("[+] " + addr + " (" + name + ") -> " + outFile);
                ok++;
            } catch (Exception e) {
                println("[X] " + t + ": " + e.getMessage());
                fail++;
            }
        }
        println("[DecompileFunctions] ok=" + ok + " fail=" + fail);
    }

    private Function resolveFunction(String spec) {
        // Try as address first (with or without 0x prefix).
        try {
            String s = spec.startsWith("0x") || spec.startsWith("0X")
                ? spec.substring(2) : spec;
            Address a = currentProgram.getAddressFactory().getAddress(s);
            if (a != null) {
                Function f = getFunctionAt(a);
                if (f == null) f = getFunctionContaining(a);
                if (f != null) return f;
            }
        } catch (Exception ignored) {}
        // Try as name.
        return getGlobalFunctions(spec).stream().findFirst().orElse(null);
    }

    private void writeOne(DecompInterface decomp, Function f, Path out) throws Exception {
        try (BufferedWriter bw = new BufferedWriter(
                new OutputStreamWriter(Files.newOutputStream(out), StandardCharsets.UTF_8))) {
            JsonWriter w = new JsonWriter(bw);
            w.beginObject();
            w.kv("addr", f.getEntryPoint().toString());
            w.kv("name", f.getName());
            w.kvNum("size", (int) f.getBody().getNumAddresses());
            w.kv("body_min", f.getBody().getMinAddress().toString());
            w.kv("body_max", f.getBody().getMaxAddress().toString());

            w.key("callers").beginArray();
            for (Function caller : f.getCallingFunctions(monitor)) {
                w.beginObject();
                w.kv("addr", caller.getEntryPoint().toString());
                w.kv("name", caller.getName());
                w.endObject();
            }
            w.endArray();

            w.key("callees").beginArray();
            for (Function callee : f.getCalledFunctions(monitor)) {
                w.beginObject();
                w.kv("addr", callee.getEntryPoint().toString());
                w.kv("name", callee.getName());
                w.endObject();
            }
            w.endArray();

            w.key("peripheral_accesses").beginArray();
            for (String p : peripheralAccesses(f)) w.value(p);
            w.endArray();

            w.key("string_xrefs").beginArray();
            for (Map<String, Object> sx : stringXrefs(f)) {
                w.beginObject();
                for (Map.Entry<String, Object> e : sx.entrySet()) {
                    Object v = e.getValue();
                    if (v instanceof Boolean) w.kvBool(e.getKey(), (Boolean) v);
                    else if (v instanceof Number) w.kvNum(e.getKey(), ((Number) v).intValue());
                    else w.kv(e.getKey(), String.valueOf(v));
                }
                w.endObject();
            }
            w.endArray();

            try {
                DecompileResults res = decomp.decompileFunction(f, DECOMP_TIMEOUT_S, monitor);
                if (res != null && res.getDecompiledFunction() != null) {
                    String c = res.getDecompiledFunction().getC();
                    w.kv("decompile", c == null ? "" : c);
                } else {
                    w.kv("decompile_error", "decompiler returned null");
                }
            } catch (Exception e) {
                w.kv("decompile_error", e.getMessage());
            }

            w.endObject();
        }
    }

    private List<String> peripheralAccesses(Function f) {
        List<String> hits = new ArrayList<>();
        ReferenceManager rm = currentProgram.getReferenceManager();
        InstructionIterator instIt = currentProgram.getListing().getInstructions(f.getBody(), true);
        while (instIt.hasNext()) {
            Instruction ins = instIt.next();
            for (Reference r : ins.getReferencesFrom()) {
                long t = r.getToAddress().getOffset();
                for (Object[] p : PERIPHERALS) {
                    long base = (Long) p[1];
                    long span = (Long) p[2];
                    if (t >= base && t < base + span) {
                        String name = (String) p[0];
                        if (!hits.contains(name)) hits.add(name);
                    }
                }
            }
        }
        Collections.sort(hits);
        return hits;
    }

    private List<Map<String, Object>> stringXrefs(Function f) {
        List<Map<String, Object>> out = new ArrayList<>();
        InstructionIterator instIt = currentProgram.getListing().getInstructions(f.getBody(), true);
        while (instIt.hasNext()) {
            Instruction ins = instIt.next();
            for (Reference r : ins.getReferencesFrom()) {
                Address tgt = r.getToAddress();
                Data d = getDataAt(tgt);
                if (d == null) continue;
                if (!d.hasStringValue()) continue;
                StringDataInstance sdi = StringDataInstance.getStringDataInstance(d);
                if (sdi == null) continue;
                String value = sdi.getStringValue();
                if (value == null) continue;
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("from", ins.getMinAddress().toString());
                entry.put("to", tgt.toString());
                entry.put("value", value);
                entry.put("is_format", FORMAT_RE.matcher(value).find());
                out.add(entry);
            }
        }
        return out;
    }

    /* ---------- Minimal streaming JSON writer (no external deps) ---------- */

    private static class JsonWriter {
        private final BufferedWriter w;
        private boolean firstInContainer = true;
        private boolean keyWritten = false;
        private final java.util.Deque<Boolean> stack = new java.util.ArrayDeque<>();

        JsonWriter(BufferedWriter w) { this.w = w; }

        private void writeSep() throws Exception {
            if (keyWritten) { keyWritten = false; return; }
            if (firstInContainer) { firstInContainer = false; }
            else w.write(",");
        }
        JsonWriter beginObject() throws Exception { writeSep(); w.write("{"); stack.push(firstInContainer); firstInContainer = true; return this; }
        JsonWriter endObject() throws Exception { w.write("}"); firstInContainer = stack.pop(); return this; }
        JsonWriter beginArray() throws Exception { writeSep(); w.write("["); stack.push(firstInContainer); firstInContainer = true; return this; }
        JsonWriter endArray() throws Exception { w.write("]"); firstInContainer = stack.pop(); return this; }
        JsonWriter key(String k) throws Exception { writeSep(); w.write("\""); w.write(escape(k)); w.write("\":"); keyWritten = true; return this; }
        JsonWriter value(String v) throws Exception { writeSep(); w.write("\""); w.write(escape(v)); w.write("\""); keyWritten = false; return this; }
        JsonWriter kv(String k, String v) throws Exception { key(k); w.write("\""); w.write(escape(v)); w.write("\""); keyWritten = false; return this; }
        JsonWriter kvNum(String k, long n) throws Exception { key(k); w.write(Long.toString(n)); keyWritten = false; return this; }
        JsonWriter kvBool(String k, boolean b) throws Exception { key(k); w.write(b ? "true" : "false"); keyWritten = false; return this; }

        private static String escape(String s) {
            if (s == null) return "";
            StringBuilder sb = new StringBuilder(s.length() + 8);
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
            return sb.toString();
        }
    }
}
