import SwiftUI

/// Server address with a connection test, and the Dynamic Island switch.
struct SettingsView: View {
    @Environment(RecipeStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @AppStorage(APIClient.serverURLKey) private var serverURL = APIClient.defaultServerURL
    @AppStorage(LiveActivityController.autoStartKey) private var autoStart = true
    @State private var test: TestState = .idle

    private enum TestState: Equatable {
        case idle, testing, success(Int), failure(String)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://192.168.2.23:8000", text: $serverURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .foregroundStyle(Color.ink)
                        .onChange(of: serverURL) { test = .idle }
                    Button {
                        Task { await testConnection() }
                    } label: {
                        HStack {
                            Text("Test connection").foregroundStyle(Color.terracotta)
                            Spacer()
                            testResult
                        }
                    }
                    .disabled(test == .testing)
                    if case .failure(let message) = test {
                        Text(message)
                            .font(.footnote)
                            .foregroundStyle(Color.muted)
                    }
                    if serverURL != APIClient.defaultServerURL {
                        Button("Use the default address") { serverURL = APIClient.defaultServerURL }
                            .foregroundStyle(Color.muted)
                    }
                } header: {
                    Text("Recipe server")
                } footer: {
                    Text("The PC running `uvicorn api.app:app --host 0.0.0.0 --port 8000`, on the same Wi-Fi.")
                }

                Section {
                    Toggle("Show steps when you leave a recipe", isOn: $autoStart)
                        .tint(.terracotta)
                } header: {
                    Text("Dynamic Island")
                } footer: {
                    Text("Watch on Instagram always shows the current step in the Dynamic Island. With this on, it also appears when you press Home or switch apps while a recipe is open.")
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.cream)
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                        .foregroundStyle(Color.terracotta)
                }
            }
        }
        // A new address takes effect for the feed as soon as Settings closes.
        .onDisappear { Task { await store.load() } }
    }

    @ViewBuilder
    private var testResult: some View {
        switch test {
        case .idle: EmptyView()
        case .testing: ProgressView()
        case .success(let count):
            Label("\(count) recipes", systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .font(.subheadline)
        case .failure:
            Label("No answer", systemImage: "xmark.circle.fill")
                .foregroundStyle(Color.heart)
                .font(.subheadline)
        }
    }

    private func testConnection() async {
        test = .testing
        do {
            let count = try await APIClient.current().recipes().count
            test = .success(count)
        } catch {
            test = .failure(error.localizedDescription)
        }
    }
}
