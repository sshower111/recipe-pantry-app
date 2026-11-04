import Foundation

/// A black-and-white icon for an ingredient (`Assets.xcassets/Ingredients/ing-<key>`; sources
/// and licenses in ios/Art/icons). Proteins show their animal (cow, pig, chicken, duck, fish),
/// every vegetable shares one mixed-vegetables icon and every fruit one fruits icon.
/// Matched on the canonical name (`Ingredient.name`: "egg", "green onion", "pork belly") by
/// whole words, first rule wins, so specific rules come before general ones ("oyster sauce"
/// is a sauce, not seafood; "eggplant" isn't an egg). No match: the tile shows the amount alone.
enum IngredientIcon {
    private static let rules: [(icon: String, words: [String])] = [
        // Specific names that would otherwise hit a broader rule.
        ("powder", ["baking powder", "baking soda", "yeast", "cornstarch", "corn starch", "starch", "gelatin",
                    "agar", "xanthan gum", "cream of tartar", "dextrose"]),
        ("vegetables", ["eggplant", "butternut squash", "sweet potato", "bell pepper", "corn"]),
        ("wheat", ["flour", "noodle", "koay teow", "barley", "tangzhong", "sourdough starter", "rice paper"]),
        ("bean", ["sugar snap pea", "snap pea", "bean curd", "bean sprout"]),
        ("dairy", ["protein milk", "fat free milk", "skim milk", "low fat milk"]),
        ("nut", ["peanut butter", "almond butter", "sesame butter", "coconut milk", "coconut cream",
                 "almond milk", "sesame paste", "tahini"]),
        ("sauce", ["oyster sauce", "fish sauce", "soy sauce", "hoisin sauce", "sauce", "vinegar", "ketchup",
                   "mayonnaise", "mayo", "mustard", "dressing", "extract", "essence", "food coloring",
                   "bouillon", "vanilla", "ponzu", "paste", "miso", "gochujang", "doenjang", "doubanjiang",
                   "jam", "pesto", "chili crisp", "chile crisp", "chilli crisp"]),
        ("chili", ["chili", "chilli", "chilly", "chile", "jalapeno", "sriracha"]),
        ("ice-cream", ["ice cream", "gelato"]),
        ("cake", ["cake", "sponge", "cheesecake filling"]),
        ("cookie", ["cookie", "biscuit", "oreo", "graham cracker", "chocolate chip", "chocolate", "cocoa",
                    "lady finger", "ladyfinger", "wafer", "butterscotch chip"]),
        ("alcohol", ["wine", "mirin", "sake", "shaoxing", "rum", "brandy", "liqueur", "vodka", "whiskey",
                     "whisky", "limoncello", "beer"]),
        ("coffee", ["coffee", "espresso", "tea", "matcha", "hojicha"]),
        ("soup", ["broth", "stock", "dashi"]),
        ("water", ["water", "ice", "soda water"]),
        ("droplet", ["oil", "honey", "syrup", "molasses", "condensed milk", "caramel", "fat"]),
        ("cheese", ["cheese", "cream cheese", "mascarpone", "ricotta", "mozzarella", "parmesan", "cheddar"]),
        // Proteins: the animal.
        ("fish", ["fish", "fishball", "salmon", "tuna", "cod", "anchovy", "sardine", "mackerel", "tilapia",
                  "seabass", "basa", "shrimp", "prawn", "crab", "lobster", "scallop", "clam", "mussel",
                  "oyster", "squid", "octopus", "abalone", "seafood"]),
        ("duck", ["duck", "duck fat"]),
        ("chicken", ["chicken", "turkey", "wing", "thigh", "drumstick", "chicken breast"]),
        ("pig", ["pork", "pork belly", "bacon", "ham", "prosciutto", "pancetta", "sausage", "chinese sausage",
                 "lap cheong", "lard", "pork fat", "trotter"]),
        ("cow", ["beef", "steak", "short rib", "rib", "brisket", "oxtail", "veal", "lamb", "mutton",
                 "ground beef"]),
        ("egg", ["egg", "egg yolk", "egg white", "yolk"]),
        // Everything else by group.
        ("dairy", ["milk", "cream", "butter", "yogurt", "yoghurt", "buttermilk", "ghee", "whey"]),
        ("salt", ["salt", "pepper", "white pepper", "black pepper", "peppercorn", "cinnamon", "spice",
                  "powder", "paprika", "cumin", "nutmeg", "clove", "star anise", "cardamom", "turmeric",
                  "five spice", "msg", "seasoning", "allspice"]),
        ("sugar", ["sugar", "rock sugar", "brown sugar", "powdered sugar", "sweetener", "marshmallow", "candy"]),
        ("bread", ["bread", "bun", "roll", "tortilla", "wrapper", "croissant", "pastry", "puff pastry", "dough",
                   "breadcrumb", "panko", "cracker"]),
        ("wheat", ["wheat", "rice", "pasta", "spaghetti", "oat", "cereal"]),
        ("bean", ["bean", "tofu", "lentil", "chickpea", "edamame", "soybean", "pea"]),
        ("nut", ["nut", "almond", "peanut", "walnut", "pecan", "pistachio", "cashew", "hazelnut", "sesame",
                 "seed", "coconut", "pine nut"]),
        ("fruits", ["apple", "banana", "plantain", "lemon", "lime", "orange", "yuzu", "grapefruit", "citrus",
                    "zest", "grape", "raisin", "cherry", "berry", "strawberry", "raspberry", "blueberry",
                    "cranberry", "blackberry", "plum", "peach", "mango", "pear", "fig", "date", "lychee",
                    "persimmon", "pineapple", "longan", "jujube", "fruit"]),
        ("herb", ["cilantro", "coriander", "parsley", "basil", "mint", "thyme", "rosemary", "dill", "oregano",
                  "bay leaf", "sage", "lemongrass", "leaf", "herb", "pandan", "shiso", "osmanthus"]),
        ("vegetables", ["carrot", "onion", "green onion", "scallion", "spring onion", "leek", "chive", "garlic",
                        "shallot", "ginger", "potato", "tomato", "cucumber", "mushroom", "radish", "daikon",
                        "pumpkin", "squash", "zucchini", "celery", "broccoli", "cauliflower", "taro", "lotus",
                        "bamboo", "vegetable", "avocado", "beet", "okra", "jicama", "yam", "asparagus",
                        "ginseng", "licorice root", "lettuce", "cabbage", "napa cabbage", "spinach", "kale",
                        "bok choy", "choy", "greens", "arugula", "watercress", "morning glory", "kombu",
                        "seaweed", "sprout"]),
    ]

    /// Compiled once: each keyword as a whole word or phrase, plurals allowed.
    private static let compiled: [(icon: String, regex: NSRegularExpression)] = rules.map { rule in
        let alternatives = rule.words
            .sorted { $0.count > $1.count }
            .map { NSRegularExpression.escapedPattern(for: $0) }
            .joined(separator: "|")
        let regex = try! NSRegularExpression(pattern: "\\b(?:\(alternatives))(?:s|es)?\\b", options: [.caseInsensitive])
        return ("ing-" + rule.icon, regex)
    }

    /// The asset name for `name`, or nil when nothing fits.
    static func asset(for name: String) -> String? {
        let range = NSRange(name.startIndex..., in: name)
        return compiled.first { $0.regex.firstMatch(in: name, range: range) != nil }?.icon
    }
}
