import Foundation
import Observation

/// The cookbook list, opened recipes and the user's marks, shared by every screen.
@Observable
final class RecipeStore {
    enum Mark { case favorite, tried }

    /// nil until the first load finishes.
    private(set) var recipes: [RecipeSummary]?
    private(set) var error: String?
    /// Full recipes already opened, by id.
    private(set) var details: [Int: Recipe] = [:]
    /// A recipe opened from the Live Activity; its screen scrolls to the current step, then clears this.
    var stepToReveal: Int?

    func load() async {
        do {
            recipes = try await APIClient.current().recipes()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    func loadRecipe(_ id: Int) async throws {
        details[id] = try await APIClient.current().recipe(id: id)
    }

    /// Flips a mark at once and puts it back if the server refuses (as the web app does).
    func toggle(_ mark: Mark, for id: Int) async {
        guard let current = value(of: mark, for: id) else { return }
        let value = !current
        set(mark, value, for: id)
        do {
            let marks = try await APIClient.current().setMarks(
                recipeId: id,
                favorite: mark == .favorite ? value : nil,
                tried: mark == .tried ? value : nil)
            set(.favorite, marks.favorite, for: id)
            set(.tried, marks.tried, for: id)
        } catch {
            set(mark, current, for: id)
        }
    }

    func thumbnailURL(_ path: String?) -> URL? {
        (try? APIClient.current())?.absoluteURL(path)
    }

    private func value(of mark: Mark, for id: Int) -> Bool? {
        if let recipe = details[id] { return mark == .favorite ? recipe.favorite : recipe.tried }
        guard let recipe = recipes?.first(where: { $0.id == id }) else { return nil }
        return mark == .favorite ? recipe.favorite : recipe.tried
    }

    /// Keeps the list and the opened recipe in step.
    private func set(_ mark: Mark, _ value: Bool, for id: Int) {
        if let index = recipes?.firstIndex(where: { $0.id == id }) {
            switch mark {
            case .favorite: recipes![index].favorite = value
            case .tried: recipes![index].tried = value
            }
        }
        switch mark {
        case .favorite: details[id]?.favorite = value
        case .tried: details[id]?.tried = value
        }
    }
}
