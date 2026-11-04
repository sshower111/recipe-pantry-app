// Draws the Live Activity's cook animation: an original chibi cook in the spirit of old-school
// Japanese anime (big head, spiky hair, headband, determined eyes) tossing a wok over a
// flaring fire. Outline only. Writes 10 frames as filled-outline SVG paths (strokes already
// converted to shapes, so they can become font glyphs) plus a preview strip:
//
//     xcrun swiftc -o /tmp/draw ios/tools/draw_cook_frames.swift && /tmp/draw ios/Art/cook-frames
//
// Then build the font: python ios/tools/make_flipbook_font.py ios/Art/cook-frames
// Coordinates are a 100x100 box, y down.

import AppKit
import CoreGraphics
import Foundation

let frameCount = 10
let lineWidth: CGFloat = 3.2

/// One frame's drawing as strokes (center lines), before outlining.
func strokes(frame: Int) -> CGPath {
    let t = Double(frame) / Double(frameCount) * 2 * .pi
    let path = CGMutablePath()
    func p(_ x: Double, _ y: Double) -> CGPoint { CGPoint(x: x, y: y) }
    func line(_ points: [(Double, Double)]) { path.addLines(between: points.map { p($0.0, $0.1) }) }

    let bob = sin(t * 2) * 0.8               // the whole body bounces twice per toss
    let lift = -max(0, sin(t)) * 6           // wok rises on the toss
    let tilt = sin(t) * 0.16                 // and tips back

    // Head: a big chibi face with a pointed chin.
    let head = CGMutablePath()
    head.move(to: p(18, 30 + bob))
    head.addQuadCurve(to: p(32, 44 + bob), control: p(19, 42 + bob))
    head.addQuadCurve(to: p(44, 30 + bob), control: p(43, 41 + bob))
    path.addPath(head)
    // Spiky hair, the tips shivering with "power".
    let jitter = { (i: Int) in sin(t * 3 + Double(i)) * 0.9 }
    line([(17, 31), (12, 19 + jitter(0)), (20, 23), (19, 9 + jitter(1)), (27, 18), (32, 4 + jitter(2)),
          (35, 17), (43, 9 + jitter(3)), (41, 21), (49, 21 + jitter(4)), (44, 30)].map { ($0.0, $0.1 + bob) })
    // Headband with two tails flapping behind.
    line([(17, 27 + bob), (44, 25 + bob)])
    line([(17, 27 + bob), (9, 22 + bob + sin(t * 2) * 3), (3, 25 + bob + sin(t * 2 + 1) * 4)])
    line([(17, 28 + bob), (8, 31 + bob + cos(t * 2) * 3), (4, 36 + bob + cos(t * 2 + 1) * 3)])
    // Determined eye and brow, grin.
    line([(34, 33 + bob), (40, 31.5 + bob)])
    line([(32, 29.5 + bob), (41, 27 + bob)])
    line([(35, 39 + bob), (39, 38 + bob)])

    // Body in a cook's jacket: V neck, belt, wide stance.
    line([(26, 45 + bob), (21, 64 + bob)])
    line([(37, 45 + bob), (39, 64 + bob)])
    line([(21, 64 + bob), (39, 64 + bob)])
    line([(27, 45 + bob), (30, 51 + bob), (34, 45 + bob)])
    line([(22, 58 + bob), (38.5, 58 + bob)])
    line([(25, 64 + bob), (19, 80), (13, 81)])
    line([(35, 64 + bob), (42, 80), (48, 81)])

    // Wok, handle and the arm holding it, tipping as it tosses.
    let pivot = p(56, 55)
    let turn = CGAffineTransform(translationX: pivot.x, y: pivot.y + lift)
        .rotated(by: -tilt)
        .translatedBy(x: -pivot.x, y: -pivot.y)
    let wok = CGMutablePath()
    wok.move(to: p(54, 55)); wok.addLine(to: p(64, 54))                         // handle
    wok.move(to: p(63, 50)); wok.addQuadCurve(to: p(97, 50), control: p(80, 70)) // bowl
    wok.move(to: p(62, 50)); wok.addLine(to: p(98, 50))                         // rim
    path.addPath(wok, transform: turn)
    let hand = p(54, 55).applying(turn)
    path.move(to: p(37, 48 + bob)); path.addQuadCurve(to: hand, control: p(44, 60 + bob))

    // Other arm: ladle dipping into the wok.
    let ladleTip = p(78, 46 + lift * 0.6)
    path.move(to: p(27, 48 + bob)); path.addQuadCurve(to: p(50, 40 + bob), control: p(36, 38 + bob))
    path.move(to: p(50, 40 + bob)); path.addLine(to: ladleTip)
    path.addEllipse(in: CGRect(x: ladleTip.x - 2.5, y: ladleTip.y - 1, width: 5, height: 3.5))

    // Food flying out of the wok and back in.
    for i in 0..<3 {
        let phase = t + Double(i) * 0.9
        let height = max(0, sin(phase)) * 24
        let x = 73 + Double(i) * 7 + cos(phase) * 3
        path.addEllipse(in: CGRect(x: x, y: 44 - height + lift, width: 4, height: 3.2))
    }

    // Fire: three curling flame tongues flaring with each toss.
    for i in 0..<3 {
        let x = 70 + Double(i) * 11
        let tip = 68 - (sin(t * 2 + Double(i) * 1.7) + 1) * 3.5 - (i == 1 ? 4 : 0)
        let sway = sin(t * 3 + Double(i)) * 2
        path.move(to: p(x - 4, 93))
        path.addQuadCurve(to: p(x + sway, tip), control: p(x - 6, 80))
        path.addQuadCurve(to: p(x + 4, 93), control: p(x + 5, 82))
    }
    // Speed lines off the wok on the up-swing.
    if sin(t) > 0.2 {
        for (i, y) in [34.0, 40, 46].enumerated() {
            line([(86 + Double(i) * 2, y - 12), (98, y - 17)])
        }
    }
    return path
}

/// Strokes turned into one filled shape (overlaps merged), ready to be a font glyph.
func outline(frame: Int) -> CGPath {
    let stroked = strokes(frame: frame).copy(strokingWithWidth: lineWidth, lineCap: .round,
                                             lineJoin: .round, miterLimit: 4)
    return stroked.normalized(using: .winding)
}

func svgPath(_ path: CGPath) -> String {
    var d = ""
    func f(_ v: CGFloat) -> String { String(format: "%.2f", v) }
    path.applyWithBlock { element in
        let pts = element.pointee.points
        switch element.pointee.type {
        case .moveToPoint: d += "M\(f(pts[0].x)) \(f(pts[0].y))"
        case .addLineToPoint: d += "L\(f(pts[0].x)) \(f(pts[0].y))"
        case .addQuadCurveToPoint: d += "Q\(f(pts[0].x)) \(f(pts[0].y)) \(f(pts[1].x)) \(f(pts[1].y))"
        case .addCurveToPoint:
            d += "C\(f(pts[0].x)) \(f(pts[0].y)) \(f(pts[1].x)) \(f(pts[1].y)) \(f(pts[2].x)) \(f(pts[2].y))"
        case .closeSubpath: d += "Z"
        @unknown default: break
        }
    }
    return d
}

let outDir = URL(fileURLWithPath: CommandLine.arguments.dropFirst().first ?? "ios/Art/cook-frames")
try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
for old in (try? FileManager.default.contentsOfDirectory(at: outDir, includingPropertiesForKeys: nil)) ?? []
where ["png", "svg"].contains(old.pathExtension) {
    try FileManager.default.removeItem(at: old)
}

// Preview strip: the 10 frames side by side in yellow on black.
let scale: CGFloat = 2
let previewSide: CGFloat = 100 * scale
let context = CGContext(data: nil, width: Int(previewSide) * frameCount, height: Int(previewSide), bitsPerComponent: 8,
                        bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
context.setFillColor(CGColor(red: 0, green: 0, blue: 0, alpha: 1))
context.fill(CGRect(x: 0, y: 0, width: previewSide * CGFloat(frameCount), height: previewSide))

for frame in 0..<frameCount {
    let shape = outline(frame: frame)
    let svg = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path fill="#F5C842" d="\(svgPath(shape))"/></svg>
    """
    try svg.write(to: outDir.appendingPathComponent("frame\(frame).svg"), atomically: true, encoding: .utf8)
    context.saveGState()
    context.translateBy(x: CGFloat(frame) * previewSide, y: previewSide)
    context.scaleBy(x: scale, y: -scale)
    context.addPath(shape)
    context.setFillColor(CGColor(red: 0.96, green: 0.78, blue: 0.26, alpha: 1))
    context.fillPath(using: .winding)
    context.restoreGState()
}
let preview = NSBitmapImageRep(cgImage: context.makeImage()!).representation(using: .png, properties: [:])!
try preview.write(to: outDir.appendingPathComponent("preview.png"))
print("\(frameCount) frames + preview.png in \(outDir.path)")
