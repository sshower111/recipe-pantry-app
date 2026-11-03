import Foundation
import Observation

/// The cookbook list, opened recipes and the user's marks, shared by every screen.
///
/// Starts from the phone's saved copy (OfflineStore) and refreshes it from the PC; when the
/// PC can't be reached, the saved copy stays on screen and `offlineSince` says how old it is.
@Observable
final class RecipeStore {
    enum Mark { case favorite, tried }

    /// nil until the first load finishes (or a saved copy exists).
    private(set) var recipes: [RecipeSummary]?
    /// Posts kept without a recipe yet ("Save for later": status `needs_recipe`), the 🔖 filter.
    private(set) var saved: [RecipeSummary] = []
    private(set) var error: String?
    /// Full recipes, by id: opened ones, plus every recipe fetched for offline in the background.
    private(set) var details: [Int: Recipe] = [:]
    /// When the saved copy on screen was last refreshed, while the PC is out of reach.
    private(set) var offlineSince: Date?
    /// A recipe opened from the Live Activity; its screen scrolls to the current step, then clears this.
    var stepToReveal: Int?
    /// Posts shared to the PC (share sheet, Check again) still being added, or finished in the
    /// last hour and not dismissed; shown above the feed.
    private(set) var ingestJobs: [IngestJob] = []
    private var dismissedJobs: Set<String> = []
    /// Set to check the jobs again right away instead of after the usual wait.
    private var checkJobsNow = false
    private var savedAt: Date?

    init() {
        if let list = OfflineStore.loadList() {
            recipes = list.recipes
            savedAt = list.savedAt
        }
        saved = OfflineStore.loadList(named: "saved")?.recipes ?? []
        details = OfflineStore.loadRecipes()
    }

    func load() async {
        do {
            let api = try APIClient.current()
            let fresh = try await api.recipes()
            let kept = (try? await api.recipes(status: "todo")) ?? saved
            recipes = fresh
            saved = kept
            error = nil
            offlineSince = nil
            savedAt = .now
            OfflineStore.saveList(fresh)
            OfflineStore.saveList(kept, named: "saved")
            OfflineStore.prune(keeping: Set((fresh + kept).map(\.id)))
            await saveMissingRecipes(fresh + kept)
        } catch {
            if recipes != nil {
                offlineSince = savedAt ?? .now  // keep the saved copy on screen
            } else {
                self.error = error.localizedDescription
            }
        }
    }

    /// Follows shared posts while any is being added: checks every 8 s, and reloads the feed
    /// when one finishes. Runs for as long as the calling task (the feed's `.task`) lives.
    func watchIngestJobs() async {
        while !Task.isCancelled {
            var wait: Double = 30  // PC out of reach, or nothing running: check now and then
            if let jobs = try? await APIClient.current().ingestJobs() {
                let wasActive = Set(ingestJobs.filter(\.isActive).map(\.id))
                let hourAgo = Date.now.addingTimeInterval(-3600)
                ingestJobs = jobs.filter { job in
                    !dismissedJobs.contains(job.id)
                        && (job.isActive || (job.finishedAt.flatMap(Self.parseDate) ?? .distantPast) > hourAgo)
                }
                if jobs.contains(where: { wasActive.contains($0.id) && !$0.isActive }) {
                    await load()  // a recipe just landed (or a saved post was checked again)
                    for job in jobs where wasActive.contains(job.id) && !job.isActive {
                        if let id = job.recipeId { try? await loadRecipe(id) }
                    }
                }
                if ingestJobs.contains(where: \.isActive) { wait = 8 }
            }
            checkJobsNow = false
            for _ in 0..<Int(wait) where !checkJobsNow && !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    func dismissJob(_ id: String) {
        dismissedJobs.insert(id)
        ingestJobs.removeAll { $0.id == id }
    }

    /// "Check again": the PC re-downloads and re-reads the post (the creator may have added
    /// the recipe since). The job shows above the feed like a share.
    func checkAgain(_ recipe: Recipe) async throws {
        let job = try await APIClient.current().ingest(recipe.video.url, refresh: true)
        ingestJobs.removeAll { $0.id == job.id }
        ingestJobs.insert(job, at: 0)
        checkJobsNow = true
    }

    /// Keep a post without a recipe (`needs_recipe`, the 🔖 list) or hide it (`not_recipe`).
    func setStatus(_ status: String, for id: Int) async throws {
        _ = try await APIClient.current().setStatus(recipeId: id, status: status)
        await load()
        try? await loadRecipe(id)
    }

    private static func parseDate(_ text: String) -> Date? {
        try? Date(text, strategy: .iso8601)
    }

    /// Throws when the PC can't be reached; the saved copy (if any) stays in `details`.
    func loadRecipe(_ id: Int) async throws {
        let recipe = try await APIClient.current().recipe(id: id)
        details[id] = recipe
        OfflineStore.saveRecipe(recipe)
    }

    /// Fetches, one at a time and quietly, the recipes never opened on this phone, so the
    /// whole cookbook works offline. Small JSON files; photos come with the feed.
    private func saveMissingRecipes(_ list: [RecipeSummary]) async {
        let missing = list.map(\.id).filter { details[$0] == nil }
        guard !missing.isEmpty, let api = try? APIClient.current() else { return }
        for id in missing {
            guard let recipe = try? await api.recipe(id: id) else { return }  // PC gone: try next launch
            details[id] = recipe
            OfflineStore.saveRecipe(recipe)
        }
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
            if let recipes { OfflineStore.saveList(recipes) }
            OfflineStore.saveList(saved, named: "saved")
            if let recipe = details[id] { OfflineStore.saveRecipe(recipe) }
        } catch {
            // Marks live on the PC, so they can't change while it's out of reach.
            set(mark, current, for: id)
        }
    }

    func thumbnailURL(_ path: String?) -> URL? {
        (try? APIClient.current())?.absoluteURL(path)
    }

    private func value(of mark: Mark, for id: Int) -> Bool? {
        if let recipe = details[id] { return mark == .favorite ? recipe.favorite : recipe.tried }
        guard let recipe = (recipes ?? []).first(where: { $0.id == id }) ?? saved.first(where: { $0.id == id })
        else { return nil }
        return mark == .favorite ? recipe.favorite : recipe.tried
    }

    /// Keeps the lists and the opened recipe in step.
    private func set(_ mark: Mark, _ value: Bool, for id: Int) {
        func apply(_ summary: inout RecipeSummary) {
            switch mark {
            case .favorite: summary.favorite = value
            case .tried: summary.tried = value
            }
        }
        if let index = recipes?.firstIndex(where: { $0.id == id }) { apply(&recipes![index]) }
        if let index = saved.firstIndex(where: { $0.id == id }) { apply(&saved[index]) }
        switch mark {
        case .favorite: details[id]?.favorite = value
        case .tried: details[id]?.tried = value
        }
    }
}
