import Foundation

/// Kitchen timers taken from a step's own wording.
enum StepTimer {
    // "28-32 minutes", "1.5 hours", "10 mins", "30 to 45 seconds"
    private static let pattern = #/(\d+(?:\.\d+)?)(?:\s*(?:-|–|to)\s*\d+(?:\.\d+)?)?\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b/#.ignoresCase()

    /// Seconds for the first duration a step mentions (the low end of a range), or nil.
    static func duration(in text: String) -> Int? {
        guard let match = text.firstMatch(of: pattern), let value = Double(match.1),
              let unit = match.2.lowercased().first else { return nil }
        let seconds = Int((value * (unit == "h" ? 3600 : unit == "m" ? 60 : 1)).rounded())
        return seconds > 0 ? seconds : nil
    }

    /// 90 -> "1:30", 3700 -> "1:01:40".
    static func clock(_ seconds: TimeInterval) -> String {
        let s = max(0, Int(seconds.rounded(.up)))
        let (h, m, sec) = (s / 3600, (s % 3600) / 60, s % 60)
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, sec) : String(format: "%d:%02d", m, sec)
    }

    /// 1200 -> "20 min", 5400 -> "1 h 30 min", 45 -> "45 s".
    static func label(_ seconds: Int) -> String {
        if seconds < 60 { return "\(seconds) s" }
        let h = seconds / 3600
        let m = Int((Double(seconds % 3600) / 60).rounded())
        return [h > 0 ? "\(h) h" : "", m > 0 ? "\(m) min" : ""].filter { !$0.isEmpty }.joined(separator: " ")
    }
}
