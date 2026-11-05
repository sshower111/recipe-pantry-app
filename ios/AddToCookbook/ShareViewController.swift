//
//  ShareViewController.swift
//  AddToCookbook
//
//  The "Remnant" entry in the share sheet: sends the shared post's link to the PC
//  (POST /api/ingest, docs/ios/api.md), which downloads and parses it in the background.
//  The new recipe then appears in the app's feed.
//

import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// The PC's address. Keep in sync with `APIClient.defaultServerURL` in the app: an extension
/// can't read the app's Settings without an App Group, which a free Apple ID can't use.
private let serverURL = URL(string: "http://192.168.2.23:8000")!

final class ShareViewController: UIViewController {
    private let model = ShareModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        model.close = { [weak self] in self?.extensionContext?.completeRequest(returningItems: nil) }
        let host = UIHostingController(rootView: ShareView(model: model))
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)
        Task { await model.send(items: extensionContext?.inputItems as? [NSExtensionItem] ?? []) }
    }
}

@MainActor @Observable
final class ShareModel {
    enum Phase: Equatable {
        case sending
        case adding           // queued on the PC
        case alreadyThere(String?)
        case failed(String)
    }

    var phase = Phase.sending
    var close: () -> Void = {}

    func send(items: [NSExtensionItem]) async {
        guard let text = await sharedText(items) else {
            phase = .failed("There's no link in what was shared.")
            return
        }
        do {
            var request = URLRequest(url: serverURL.appending(path: "api/ingest"), timeoutInterval: 8)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(["url": text])
            let (data, response) = try await URLSession.shared.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard status == 202, var job = try? JSONDecoder().decode(Job.self, from: data) else {
                let detail = (try? JSONDecoder().decode([String: String].self, from: data))?["detail"]
                phase = .failed(detail ?? "The PC answered HTTP \(status).")
                return
            }
            // A post already in Remnant finishes almost at once: say so instead of "adding".
            for _ in 0..<5 where job.status == "queued" || job.status == "running" {
                try? await Task.sleep(for: .milliseconds(400))
                if let (data, _) = try? await URLSession.shared.data(from: serverURL.appending(path: "api/ingest/\(job.id)")),
                   let latest = try? JSONDecoder().decode(Job.self, from: data) {
                    job = latest
                }
            }
            if job.status == "done", job.result == "skipped" {
                phase = .alreadyThere(job.title)
            } else if job.status == "failed" {
                phase = .failed(job.message ?? "The PC couldn't add it.")
            } else {
                phase = .adding
                try? await Task.sleep(for: .seconds(2))
                close()
            }
        } catch {
            phase = .failed("Couldn't reach the PC at \(serverURL.host() ?? "?"). Is it on, with the server running, and is the phone on home Wi-Fi?")
        }
    }

    /// The shared link, or shared text (the server finds the link in it).
    private func sharedText(_ items: [NSExtensionItem]) async -> String? {
        let providers = items.flatMap { $0.attachments ?? [] }
        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            if let url = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL {
                return url.absoluteString
            }
        }
        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            if let text = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String,
               text.contains("http") {
                return text
            }
        }
        return items.compactMap { $0.attributedContentText?.string }.first { $0.contains("http") }
    }

    private struct Job: Decodable {
        let id: String
        let status: String
        let result: String?
        let title: String?
        let message: String?
    }
}

private let cream = Color(red: 0xFA / 255, green: 0xF8 / 255, blue: 0xF5 / 255)
private let ink = Color(red: 0x2B / 255, green: 0x26 / 255, blue: 0x22 / 255)
private let muted = Color(red: 0x8A / 255, green: 0x81 / 255, blue: 0x7A / 255)
private let terracotta = Color(red: 0xC8 / 255, green: 0x6D / 255, blue: 0x51 / 255)

struct ShareView: View {
    let model: ShareModel

    var body: some View {
        VStack(spacing: 14) {
            icon
                .font(.system(size: 34, weight: .medium))
                .foregroundStyle(terracotta)
                .frame(height: 44)
            Text(title)
                .font(.system(size: 26, design: .serif))
                .foregroundStyle(ink)
                .multilineTextAlignment(.center)
            Text(detail)
                .font(.subheadline)
                .foregroundStyle(muted)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            if model.phase != .sending {
                Button("Done") { model.close() }
                    .font(.body.weight(.medium))
                    .foregroundStyle(.white)
                    .frame(maxWidth: 220, minHeight: 46)
                    .background(terracotta, in: .capsule)
                    .padding(.top, 6)
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(cream)
        .sensoryFeedback(.success, trigger: model.phase) { _, phase in phase == .adding }
    }

    @ViewBuilder
    private var icon: some View {
        switch model.phase {
        case .sending: ProgressView().tint(terracotta).scaleEffect(1.4)
        case .adding, .alreadyThere: Image(systemName: "checkmark.circle")
        case .failed: Image(systemName: "exclamationmark.triangle")
        }
    }

    private var title: String {
        switch model.phase {
        case .sending: "Sending to Remnant…"
        case .adding: "Sent to Remnant"
        case .alreadyThere: "Already in Remnant"
        case .failed: "Couldn't add it"
        }
    }

    private var detail: String {
        switch model.phase {
        case .sending: "Sending the link to your PC."
        case .adding: "Your PC is reading the video. The recipe shows up in the feed in a couple of minutes."
        case .alreadyThere(let title): title.map { "“\($0)” is saved already." } ?? "This post is saved already."
        case .failed(let message): message
        }
    }
}
