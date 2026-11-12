import Foundation

/// Where EOD keeps its engine, config files and cache: ~/Library/Application Support/EOD.
/// The Python engine resolves every path relative to extract.py, so the app copies the
/// bundled engine here and runs it from here. Config files (exclude.txt, repos.txt,
/// polish.off, send.txt, ...) and cache/ live beside it, exactly as in ~/.hammerspoon.
enum Paths {
    static let support: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("EOD", isDirectory: true)
    }()
    static var cache: URL { support.appendingPathComponent("cache", isDirectory: true) }
    static var script: URL { support.appendingPathComponent("extract.py") }
    static func cacheFile(_ name: String) -> URL { cache.appendingPathComponent(name) }
}

enum EngineInstaller {
    /// Copy the engine shipped inside the app bundle into Application Support when the
    /// bundled version differs from the installed one. Only engine files are replaced:
    /// the user's config files and cache are never touched.
    static func installIfNeeded() {
        let fm = FileManager.default
        guard let bundled = Bundle.main.resourceURL?.appendingPathComponent("engine", isDirectory: true),
              fm.fileExists(atPath: bundled.path) else { return }
        try? fm.createDirectory(at: Paths.cache, withIntermediateDirectories: true)
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "0"
        let marker = Paths.support.appendingPathComponent(".engine-version")
        if (try? String(contentsOf: marker, encoding: .utf8)) == version,
           fm.fileExists(atPath: Paths.script.path) { return }
        for name in ["extract.py", "eod", "bin", "exclude.txt.example"] {
            let src = bundled.appendingPathComponent(name)
            let dst = Paths.support.appendingPathComponent(name)
            guard fm.fileExists(atPath: src.path) else { continue }
            try? fm.removeItem(at: dst)
            try? fm.copyItem(at: src, to: dst)
        }
        try? version.write(to: marker, atomically: true, encoding: .utf8)
    }
}

/// Runs extract.py and hands back what it printed. The engine answers one line,
/// "<TAG> <path>" (CHANGED / UNCHANGED / WEEKLY / SHARE / SENT ...).
enum Engine {
    static let python: String = {
        for p in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
            where FileManager.default.isExecutableFile(atPath: p) { return p }
        return "/usr/bin/python3"
    }()

    struct Result { let code: Int32; let out: String; let err: String
        var tagged: (tag: String, rest: String)? {
            let line = out.trimmingCharacters(in: .whitespacesAndNewlines).components(separatedBy: "\n").last ?? ""
            guard let sp = line.firstIndex(of: " ") else { return nil }
            return (String(line[..<sp]), String(line[line.index(after: sp)...]))
        }
    }

    @discardableResult
    static func run(_ args: [String], timeout: TimeInterval = 300,
                    done: @escaping (Result) -> Void) -> Process? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = [Paths.script.path] + args
        p.currentDirectoryURL = Paths.support
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        env["LANG"] = "en_US.UTF-8"
        p.environment = env
        let outPipe = Pipe(), errPipe = Pipe()
        p.standardOutput = outPipe; p.standardError = errPipe
        var outData = Data(), errData = Data()
        let q = DispatchQueue(label: "eod.engine.read")
        outPipe.fileHandleForReading.readabilityHandler = { h in let d = h.availableData; q.sync { outData.append(d) } }
        errPipe.fileHandleForReading.readabilityHandler = { h in let d = h.availableData; q.sync { errData.append(d) } }
        p.terminationHandler = { proc in
            outPipe.fileHandleForReading.readabilityHandler = nil
            errPipe.fileHandleForReading.readabilityHandler = nil
            let restOut = outPipe.fileHandleForReading.readDataToEndOfFile()
            let restErr = errPipe.fileHandleForReading.readDataToEndOfFile()
            let (o, e): (Data, Data) = q.sync { (outData + restOut, errData + restErr) }
            let r = Result(code: proc.terminationStatus,
                           out: String(decoding: o, as: UTF8.self), err: String(decoding: e, as: UTF8.self))
            DispatchQueue.main.async { done(r) }
        }
        do { try p.run() } catch {
            Log.write("could not start python: \(error)")
            DispatchQueue.main.async { done(Result(code: -1, out: "", err: "could not start python3")) }
            return nil
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + timeout) { if p.isRunning { p.terminate() } }
        return p
    }
}

enum Log {
    static func write(_ s: String) {
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(s)\n"
        let url = Paths.cacheFile("app.log")
        if let h = try? FileHandle(forWritingTo: url) { h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close() }
        else { try? line.write(to: url, atomically: true, encoding: .utf8) }
    }
}

enum Day {
    static let fmt: DateFormatter = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX"); return f }()
    static func today() -> String { fmt.string(from: Date()) }
    static func shift(_ d: String, by days: Int) -> String? {
        guard let date = fmt.date(from: d),
              let n = Calendar.current.date(byAdding: .day, value: days, to: date) else { return nil }
        return fmt.string(from: n)
    }
}
