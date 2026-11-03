import Foundation

/// The phone's saved copy of the cookbook, so it opens instantly and still works when the PC
/// is off or out of reach (away from home Wi-Fi). JSON files in Application Support:
/// `recipes.json` (the feed) and `recipes/<id>.json` (full recipes). Photos are kept by
/// URLCache (see Thumbnail).
enum OfflineStore {
    private static let directory: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = base.appending(path: "Offline", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: dir.appending(path: "recipes"), withIntermediateDirectories: true)
        return dir
    }()

    private static var listFile: URL { directory.appending(path: "recipes.json") }

    private static func recipeFile(_ id: Int) -> URL { directory.appending(path: "recipes/\(id).json") }

    static func loadList() -> (recipes: [RecipeSummary], savedAt: Date)? {
        guard let recipes = read([RecipeSummary].self, from: listFile) else { return nil }
        let savedAt = (try? listFile.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
        return (recipes, savedAt ?? .now)
    }

    static func saveList(_ recipes: [RecipeSummary]) {
        write(recipes, to: listFile)
    }

    static func loadRecipes() -> [Int: Recipe] {
        let files = (try? FileManager.default.contentsOfDirectory(at: directory.appending(path: "recipes"),
                                                                 includingPropertiesForKeys: nil)) ?? []
        let recipes = files.compactMap { read(Recipe.self, from: $0) }
        return Dictionary(recipes.map { ($0.id, $0) }, uniquingKeysWith: { _, last in last })
    }

    static func saveRecipe(_ recipe: Recipe) {
        write(recipe, to: recipeFile(recipe.id))
    }

    /// Drops saved recipes the server no longer lists (deleted or re-classified on the PC).
    static func prune(keeping ids: Set<Int>) {
        let files = (try? FileManager.default.contentsOfDirectory(at: directory.appending(path: "recipes"),
                                                                 includingPropertiesForKeys: nil)) ?? []
        for file in files where Int(file.deletingPathExtension().lastPathComponent).map(ids.contains) == false {
            try? FileManager.default.removeItem(at: file)
        }
    }

    private static func read<T: Decodable>(_ type: T.Type, from url: URL) -> T? {
        (try? Data(contentsOf: url)).flatMap { try? JSONDecoder().decode(type, from: $0) }
    }

    private static func write<T: Encodable>(_ value: T, to url: URL) {
        guard let data = try? JSONEncoder().encode(value) else { return }
        try? data.write(to: url, options: .atomic)
    }
}
