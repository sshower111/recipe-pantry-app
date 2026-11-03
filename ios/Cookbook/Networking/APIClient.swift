import Foundation

enum APIError: LocalizedError {
    case badServerURL(String)
    case http(status: Int, detail: String?)

    var errorDescription: String? {
        switch self {
        case .badServerURL(let text):
            "“\(text)” isn't a valid server address."
        case .http(let status, let detail):
            detail.map { "\($0) (HTTP \(status))" } ?? "The server answered HTTP \(status)."
        }
    }
}

/// Talks to the FastAPI server on the Mac (`uvicorn api.app:app`). See docs/ios/api.md.
struct APIClient {
    /// UserDefaults / @AppStorage key for the server address set in Settings.
    static let serverURLKey = "serverURL"
    /// The Windows PC that runs the backend (docs/ios/README.md, section 3); the Settings
    /// screen can change it. Keep the PC on this address with a DHCP reservation.
    static let defaultServerURL = "http://192.168.2.23:8000"

    let baseURL: URL
    var session: URLSession = .shared

    /// A client for the address currently saved in Settings.
    static func current() throws -> APIClient {
        let text = UserDefaults.standard.string(forKey: serverURLKey) ?? defaultServerURL
        guard let url = URL(string: text.trimmingCharacters(in: .whitespaces)), url.host() != nil else {
            throw APIError.badServerURL(text)
        }
        return APIClient(baseURL: url)
    }

    /// Ready recipes by default; `status: "todo"` gives posts kept without a recipe yet.
    func recipes(status: String? = nil) async throws -> [RecipeSummary] {
        try await get("api/recipes", query: status.map { [URLQueryItem(name: "status", value: $0)] } ?? [])
    }

    func recipe(id: Int) async throws -> Recipe {
        try await get("api/recipes/\(id)")
    }

    /// Sets either mark (or both); the server returns the stored values.
    func setMarks(recipeId: Int, favorite: Bool? = nil, tried: Bool? = nil) async throws -> Marks {
        var body: [String: Bool] = [:]
        body["favorite"] = favorite
        body["tried"] = tried
        return try await send(jsonRequest("api/recipes/\(recipeId)", method: "PATCH", body: body))
    }

    /// Relabels a post without an ingredient list: `needs_recipe` (keep) or `not_recipe` (hide).
    func setStatus(recipeId: Int, status: String) async throws -> Marks {
        try await send(jsonRequest("api/recipes/\(recipeId)", method: "PATCH", body: ["status": status]))
    }

    /// Queues a post on the PC; `refresh` re-reads one already stored ("Check again").
    func ingest(_ url: String, refresh: Bool = false) async throws -> IngestJob {
        struct Body: Encodable { let url: String; let refresh: Bool }
        return try await send(jsonRequest("api/ingest", method: "POST", body: Body(url: url, refresh: refresh)))
    }

    private func jsonRequest(_ path: String, method: String, body: some Encodable) throws -> URLRequest {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        return request
    }

    func ingredients() async throws -> [PantryIngredient] {
        try await get("api/ingredients")
    }

    func pantry(have: [String], limit: Int? = nil) async throws -> [PantryMatch] {
        var query = have.map { URLQueryItem(name: "have", value: $0) }
        if let limit { query.append(URLQueryItem(name: "limit", value: String(limit))) }
        return try await get("api/pantry", query: query)
    }

    /// Posts shared from the phone and being added on the PC, newest first.
    func ingestJobs() async throws -> [IngestJob] {
        try await get("api/ingest")
    }

    /// `thumbnail_url` is a path on the server, e.g. `/api/recipes/1/thumbnail`.
    func absoluteURL(_ path: String?) -> URL? {
        guard let path else { return nil }
        return URL(string: path, relativeTo: baseURL)?.absoluteURL
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        var url = baseURL.appending(path: path)
        if !query.isEmpty { url.append(queryItems: query) }
        return try await send(URLRequest(url: url))
    }

    private func send<T: Decodable>(_ request: URLRequest) async throws -> T {
        var request = request
        // Away from home the PC simply doesn't answer; give up quickly (the default is 60 s)
        // so the saved copy stays useful instead of a spinner.
        request.timeoutInterval = 8
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            // FastAPI errors look like {"detail": "Recipe not found"}.
            let detail = (try? JSONDecoder().decode([String: String].self, from: data))?["detail"]
            throw APIError.http(status: status, detail: detail)
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: data)
    }
}
