import SwiftUI

/// Build step 1 check (docs/ios/README.md, section 7): every ready recipe's title
/// from the server. Replaced by the cookbook feed in step 2.
struct ContentView: View {
    @State private var recipes: [RecipeSummary] = []
    @State private var error: String?
    @State private var isLoading = true

    var body: some View {
        NavigationStack {
            Group {
                if let error {
                    ContentUnavailableView {
                        Label("Can't reach the server", systemImage: "wifi.exclamationmark")
                    } description: {
                        Text(error)
                    } actions: {
                        Button("Try again") { Task { await load() } }
                            .tint(.terracotta)
                    }
                } else if isLoading {
                    ProgressView()
                } else {
                    List(recipes) { recipe in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(recipe.title)
                                .font(.serifTitle(18))
                                .foregroundStyle(Color.ink)
                            Text("\(recipe.ingredientCount) ingredients · \(recipe.stepCount) steps")
                                .font(.footnote)
                                .foregroundStyle(Color.muted)
                        }
                        .listRowBackground(Color.cream)
                    }
                    .scrollContentBackground(.hidden)
                    .refreshable { await load() }
                }
            }
            .background(Color.cream)
            .navigationTitle(isLoading || error != nil ? "Cookbook" : "\(recipes.count) recipes")
        }
        .task { await load() }
    }

    private func load() async {
        do {
            recipes = try await APIClient.current().recipes()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }
}

#Preview {
    ContentView()
}
