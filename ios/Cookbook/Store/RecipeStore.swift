import Foundation
import Observation

/// The cookbook list and the user's marks, shared by every screen.
@Observable
final class RecipeStore {
    /// nil until the first load finishes.
    private(set) var recipes: [RecipeSummary]?
    private(set) var error: String?

    func load() async {
        do {
            recipes = try await APIClient.current().recipes()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// Flips the heart at once and puts it back if the server refuses (as the web app does).
    func toggleFavorite(_ id: Int) async {
        guard let recipe = recipes?.first(where: { $0.id == id }) else { return }
        let favorite = !recipe.favorite
        update(id) { $0.favorite = favorite }
        do {
            let marks = try await APIClient.current().setMarks(recipeId: id, favorite: favorite)
            update(id) { $0.favorite = marks.favorite; $0.tried = marks.tried }
        } catch {
            update(id) { $0.favorite = !favorite }
        }
    }

    func thumbnailURL(_ path: String?) -> URL? {
        (try? APIClient.current())?.absoluteURL(path)
    }

    private func update(_ id: Int, _ change: (inout RecipeSummary) -> Void) {
        guard let index = recipes?.firstIndex(where: { $0.id == id }) else { return }
        change(&recipes![index])
    }
}
