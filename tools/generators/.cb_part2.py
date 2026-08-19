
    # ---- B. CODE EXPLANATION SKILLS ---------------------------------------

    def _cb_explain_request_detect(cmd):
        if re.search(r"\bexplain\s+(?:this|that|the|my)?\s*(?:code|script|"
                     r"snippet|program|function)\b", cmd, re.I) or \
           re.search(r"\bwhat\s+(?:does|do)\s+(?:this|that|the|my)\s+"
                     r"(?:code|script|snippet|program|function)\s+do\b",
                     cmd, re.I) or \
           re.search(r"\bwalk\s+me\s+through\s+(?:this|the|my)\s+(?:code|"
                     r"program)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_explain_request_fn(app, cmd):
        code = _cb_payload(cmd, r"\b(?:explain|walk\s+me\s+through)\b.*?"
                           r"(?:code|script|snippet|program|function)\b")
        if code:
            return _llm_reply(app, "Explain this code clearly, step by "
                                   "step, then summarize what it does "
                                   "overall: %s" % code)
        return ("Paste the code after your request, sir - for example: "
                "'explain this code: def f(n): ...'\n"
                "Meanwhile I can explain any concept directly - try 'how "
                "does recursion work' or 'what is big o notation', sir.")

    reg_fn("cb_explain_request", _cb_explain_request_detect,
           _cb_explain_request_fn)

    PROGRAMMING_CONCEPTS = [
        (("variable",),
         "A variable is a named container for a value. In Python: age = 25 "
         "stores 25 under the name 'age' so you can reuse or change it "
         "later, sir."),
        (("constant",),
         "A constant is a value fixed for a program's lifetime. Python "
         "convention: MAX_SIZE = 100 in caps; languages like Java enforce "
         "it with 'final' or 'const', sir."),
        (("function",),
         "A function bundles reusable steps: def greet(name): return "
         "'Hello ' + name. Call it with greet('Sam') whenever needed, sir."),
        (("parameter vs argument", "parameter", "argument"),
         "Parameters are the placeholders in a function definition "
         "(def f(x)); arguments are the actual values passed when calling "
         "(f(5)), sir."),
        (("recursion",),
         "Recursion is a function calling itself on a smaller input until "
         "a base case stops it:\ndef fact(n):\n    return 1 if n <= 1 else "
         "n * fact(n - 1)\nAlways define the base case first, or it never "
         "ends, sir."),
        (("loop", "iteration"),
         "A loop repeats work: 'for x in items:' walks a collection; "
         "'while condition:' repeats until the condition turns false. "
         "Off-by-one bugs live here, sir."),
        (("array data structure", "arrays"),
         "An array is an ordered, index-addressed sequence of elements. "
         "arr[0] is the first element in most languages; arrays give O(1) "
         "access by index, sir."),
        (("linked list",),
         "A linked list stores nodes, each holding a value and a pointer "
         "to the next node. Insert/delete at the head is O(1), but "
         "reaching item k costs O(k) walking, unlike arrays, sir."),
        (("stack data structure", "stack"),
         "A stack is last-in, first-out: push adds to the top, pop removes "
         "from the top. Function call stacks and undo history both work "
         "this way, sir."),
        (("queue data structure", "queue"),
         "A queue is first-in, first-out: enqueue at the back, dequeue "
         "from the front - exactly like a fair waiting line. Printers and "
         "task schedulers use them, sir."),
        (("hash table", "hash map", "hashmap", "dictionary python"),
         "A hash table maps keys to values using a hash function for O(1) "
         "average lookups. Python: d = {'a': 1}; d['a']. Collisions are "
         "resolved by chaining or open addressing, sir."),
        (("binary tree",),
         "A binary tree is a hierarchy where each node has up to two "
         "children (left/right). Traversals come in inorder, preorder, "
         "and postorder flavors, sir."),
        (("binary search tree", "bst"),
         "A binary search tree keeps left child < parent < right child, so "
         "search, insert, and delete average O(log n). Unbalanced trees "
         "degrade toward O(n); AVL and red-black trees self-balance, sir."),
        (("graph data structure", "graphs"),
         "A graph is nodes connected by edges - social networks, maps, "
         "dependency trees. Represent with adjacency lists; traverse with "
         "BFS (shortest hops) or DFS (deep exploration), sir."),
        (("heap data structure", "heap"),
         "A heap is a complete binary tree keeping the smallest (min-heap) "
         "or largest (max-heap) element at the root, giving O(log n) "
         "insert/extract. Priority queues are built on heaps, sir."),
        (("sorting algorithm", "sorting algorithms"),
         "Sorting orders elements: quicksort averages O(n log n) with "
         "in-place partitioning, mergesort guarantees O(n log n) and "
         "stability, bubblesort is O(n^2) teaching material, sir."),
        (("big o notation", "time complexity"),
         "Big O describes how runtime grows with input size: O(1) "
         "constant, O(log n) halving (binary search), O(n) linear scan, "
         "O(n log n) good sorts, O(n^2) nested loops, sir."),
        (("space complexity",),
         "Space complexity measures extra memory an algorithm needs "
         "relative to input size - recursion depth counts, and trading "
         "memory (memoization) often buys speed, sir."),
        (("dynamic programming",),
         "Dynamic programming solves overlapping subproblems once and "
         "stores results (memoization or tabulation). Fibonacci naively "
         "is O(2^n); with DP it drops to O(n), sir."),
        (("greedy algorithm",),
         "A greedy algorithm takes the locally best choice at every step, "
         "hoping it leads to a global optimum. Works for coin change with "
         "canonical coins and Huffman coding; fails elsewhere, sir."),
        (("divide and conquer",),
         "Divide and conquer splits a problem, solves the pieces, then "
         "combines: mergesort divides the array, sorts halves, merges "
         "them in O(n log n), sir."),
        (("pointer", "pointers"),
         "A pointer is a variable holding a memory address. C: int *p = "
         "&x; dereference with *p. Misuse causes segfaults and leaks - "
         "Python hides pointers behind references, sir."),
        (("object oriented programming", "oop"),
         "OOP models software as objects bundling state (attributes) and "
         "behavior (methods). Pillars: encapsulation, inheritance, "
         "polymorphism, abstraction, sir."),
        (("class in programming", "classes programming"),
         "A class is a blueprint for objects:\nclass Dog:\n    def "
         "bark(self):\n        print('Woof')\nEach instance carries its "
         "own attributes while sharing methods, sir."),
        (("inheritance",),
         "Inheritance lets a child class reuse and extend a parent: class "
         "Puppy(Dog): inherits bark() and may override it. Favor "
         "composition when hierarchies get tangled, sir."),
        (("polymorphism",),
         "Polymorphism lets different types answer the same call their own "
         "way: dog.speak() vs cat.speak(). Duck typing judges by behavior, "
         "not declared type, sir."),
        (("encapsulation",),
         "Encapsulation hides internal state behind methods. Python "
         "signals privacy with _leading_underscores and @property getters "
         "- protecting invariants instead of secrecy, sir."),
        (("abstraction",),
         "Abstraction exposes what something does, hiding how: you call "
         "list.sort() without knowing Timsort details. Abstract base "
         "classes formalize contracts, sir."),
        (("closure", "closures"),
         "A closure is a function capturing variables from its enclosing "
         "scope:\ndef counter():\n    n = 0\n    def inc():\n        "
         "nonlocal n; n += 1; return n\n    return inc, sir."),
        (("callback function", "callbacks"),
         "A callback is a function passed to another to run later - "
         "button.on_click(handler) or array.map(fn). Async code chains "
         "them; too many nesting levels earn the name 'callback hell', sir."),
        (("promise javascript", "promises javascript"),
         "A promise represents a future result: pending, fulfilled, or "
         "rejected. Chain with .then/.catch; await makes the same flow "
         "read sequentially, sir."),
        (("async await", "async/await"),
         "async/await writes asynchronous code that reads synchronously:"
         "\nasync def get_data():\n    r = await fetch(url)\nThe event "
         "loop interleaves tasks during awaits instead of blocking, sir."),
        (("event loop",),
         "The event loop is a scheduler that runs callbacks when their "
         "events fire, letting one thread serve thousands of connections. "
         "Node.js and asyncio are built around it, sir."),
        (("thread", "threading"),
         "A thread is an independent execution stream sharing process "
         "memory - cheap concurrency, but shared state needs locks. "
         "Python's GIL serializes CPU-bound threads; use processes for "
         "parallel compute, sir."),
        (("process operating system", "processes"),
         "A process owns its own memory space; threads live inside one. "
         "Processes isolate crashes and bypass the GIL via multiprocessing,"
         " at the cost of heavier startup and IPC, sir."),
        (("deadlock",),
         "A deadlock is when threads hold resources and wait on each other "
         "forever - the classic dining philosophers. Prevent by ordering "
         "lock acquisition or using timeouts, sir."),
        (("race condition",),
         "A race condition happens when correctness depends on thread "
         "timing: two increments interleave and one update vanishes. Fix "
         "with locks, atomics, or queues, sir."),
        (("garbage collection",),
         "Garbage collection automatically frees unreachable objects. "
         "Python primarily reference-counts and breaks cycles with a "
         "generational collector, sir."),
        (("memory leak",),
         "A memory leak grows usage over time because references linger: "
         "global caches, lingering listeners, cycles. Profile with "
         "tracemalloc or heap snapshots to find who holds the memory, sir."),
        (("regular expression", "regex"),
         "Regex describes text patterns: r'\d{3}-\d{4}' matches phone "
         "numbers. Greedy quantifiers over-match; anchor with ^ $ and test "
         "on regex101.com, sir."),
        (("json format", "json data"),
         "JSON is a text data format of objects, arrays, strings, numbers, "
         "booleans, and null. Python: json.loads(text) parses, "
         "json.dumps(obj, indent=2) pretty-prints, sir."),
        (("rest api", "restful api"),
         "REST exposes resources at URLs using HTTP verbs: GET /users "
         "lists, POST /users creates, GET/PUT/DELETE /users/42 operates on "
         "one. Statelessness and proper status codes are the contract, sir."),
        (("http protocol",),
         "HTTP is the request-response protocol of the web: method, path, "
         "headers, body going in, status plus payload coming back. HTTPS "
         "wraps it in TLS encryption, sir."),
        (("https",),
         "HTTPS is HTTP over TLS: certificates authenticate the server and "
         "traffic is encrypted, stopping eavesdropping and tampering. It "
         "is mandatory for modern APIs and cookies, sir."),
        (("tcp protocol",),
         "TCP guarantees ordered, reliable delivery with handshakes, "
         "retransmits, and flow control - ideal for web and files. UDP "
         "skips guarantees to win latency, ideal for games and voice, sir."),
        (("udp protocol",),
         "UDP sends datagrams without handshake or retries - tiny "
         "overhead, no delivery promise. DNS lookups, video streams, and "
         "online games trade reliability for speed here, sir."),
        (("sql language",),
         "SQL is the language of relational databases: SELECT name FROM "
         "users WHERE age > 21 ORDER BY name. JOIN combines tables on "
         "keys; GROUP BY aggregates, sir."),
        (("nosql",),
         "NoSQL databases drop the relational model: document stores "
         "(MongoDB), key-value (Redis), wide-column (Cassandra), graph "
         "(Neo4j). They scale horizontally and flex schema, trading some "
         "consistency, sir."),
        (("database index", "database indexes"),
         "An index is a lookup structure (usually B-tree) that turns full "
         "table scans into fast seeks - like a book index. They speed "
         "reads and slow writes; index columns you filter and join on, sir."),
        (("acid transactions", "acid database"),
         "ACID is transaction safety: Atomicity (all-or-nothing), "
         "Consistency (valid states only), Isolation (no intermediate "
         "peeking), Durability (committed survives crashes), sir."),
        (("database normalization", "normalization"),
         "Normalization structures tables to remove redundancy: separate "
         "customers from orders, reference by foreign key. 3NF is the "
         "usual target; denormalize deliberately for read speed, sir."),
        (("orm",),
         "An ORM maps rows to objects: session.query(User).filter_by(age > "
         "21) instead of SQL strings. Convenient and safe from injection, "
         "but know the SQL it emits for performance, sir."),
        (("mvc pattern", "model view controller"),
         "MVC separates Model (data), View (presentation), Controller "
         "(input wiring). Django, Rails, and Spring all riff on it; the "
         "goal is independent change of each layer, sir."),
        (("singleton pattern", "singleton"),
         "Singleton ensures one shared instance: module-level objects in "
         "Python or __new__ guarding creation. Handy for config and "
         "logging; hidden global state is the price, sir."),
        (("factory pattern", "factory"),
         "Factory centralizes object creation behind a function or class, "
         "so callers ask for 'a shape' and receive circles or squares by "
         "config - decoupling construction from use, sir."),
        (("observer pattern", "observer"),
         "Observer lets subjects notify subscribers: UI events, webhooks, "
         "pub/sub brokers. Decouples producers from consumers; remember "
         "to unsubscribe or leak listeners, sir."),
        (("dependency injection",),
         "Dependency injection supplies collaborators from outside "
         "(constructor parameters) instead of hardcoding them, making "
         "components testable with mocks and swappable in production, sir."),
        (("unit testing",),
         "Unit testing verifies pieces in isolation:\ndef test_add():\n"
         "    assert add(2, 3) == 5\nFast, focused tests catch regressions "
         "the moment they appear, sir."),
        (("test driven development", "tdd"),
         "TDD flips the order: write a failing test, write the minimum "
         "code to pass, refactor. The suite becomes both spec and safety "
         "net, sir."),
        (("version control", "git version control"),
         "Version control records history and enables branching: commit "
         "snapshots, diff reviews, safe experiments. Git tracks content "
         "locally; remotes like GitHub share and synchronize it, sir."),
        (("continuous integration", "ci cd", "cicd"),
         "CI builds and tests every push automatically; CD deploys passing "
         "builds to staging or production. GitHub Actions, GitLab CI, and "
         "Jenkins are the usual engines, sir."),
        (("agile methodology", "scrum"),
         "Agile ships in short iterations with feedback loops. Scrum "
         "packages it into sprints, standups, backlog grooming, and "
         "retrospectives, sir."),
        (("code review",),
         "Code review is peers reading diffs before merge - catching bugs,"
         " spreading knowledge, and enforcing standards. Small PRs and "
         "concrete comments make them fast and kind, sir."),
        (("technical debt",),
         "Technical debt is the future cost of today's shortcut - "
         "workarounds, missing tests, outdated docs. Interest accrues as "
         "slowness; repay via refactoring budgeted over time, sir."),
        (("refactoring",),
         "Refactoring restructures code without changing behavior: extract"
         " functions, rename for clarity, collapse duplication. Tests "
         "green before and after is the discipline, sir."),
        (("design patterns", "design pattern"),
         "Design patterns are reusable solutions cataloged by the 'Gang of "
         "Four': Singleton, Factory, Observer, Strategy, Decorator. "
         "Vocabulary for designs, not goals in themselves, sir."),
        (("microservices",),
         "Microservices split a system into independently deployable "
         "services owning their data. Scaling and team autonomy improve; "
         "distributed debugging and eventual consistency are the tax, sir."),
        (("monolith architecture", "monolith"),
         "A monolith is one deployable application containing all features"
         " - simple to develop and trace early on. Many teams start here "
         "and extract services only when pain demands, sir."),
        (("graphql",),
         "GraphQL lets clients specify exactly which fields they want in "
         "one query: query { user(id: 1) { name posts { title } } }. One "
         "endpoint, typed schema, no over-fetching, sir."),
        (("websocket",),
         "WebSockets upgrade HTTP to a persistent two-way channel - chat, "
         "live dashboards, games. Server pushes anytime: ws.send(...) both "
         "directions, sir."),
        (("caching",),
         "Caching stores computed results close to the asker: browser, "
         "CDN, Redis. Rules of thumb: cache reads, invalidate on write, "
         "set TTLs, and measure hit rates, sir."),
        (("load balancing",),
         "Load balancing spreads traffic across servers - round robin, "
         "least connections, IP hash. Health checks pull dead instances "
         "out of rotation automatically, sir."),
        (("containerization", "docker container"),
         "Containerization packages app plus dependencies into an image "
         "running identically anywhere: docker build -t app . then docker "
         "run app. Images layer; containers are running instances, sir."),
        (("virtual machine", "vm vs container"),
         "A VM virtualizes hardware and boots a full guest OS (heavy, "
         "minutes); a container shares the host kernel (light, "
         "milliseconds). Containers trade isolation strength for density, "
         "sir."),
    ]

    def _cb_register_concept(idx, triggers, reply):
        alts = "|".join(re.escape(t) for t in triggers)
        pat = re.compile(
            r"(?:\b(?:what\s+is|what's|whats|explain|define|tell\s+me\s+"
            r"about|how\s+(?:do|does|to|can)(?:\s+i|\s+you|\s+we|\s+one)?)"
            r"\s+(?:a\s+|an\s+|the\s+)?(?:%s)s?\b"
            r"|\b(?:%s)s?\s+(?:example|examples|explained|in programming)\b)"
            % (alts, alts), re.I)

        def detect(cmd, _pat=pat):
            if _pat.search(cmd):
                return {"cmd": cmd}
            return None

        def execute(app, cmd, _reply=reply):
            return _reply

        brain.reg_fn("cb_concept_%02d" % idx, detect, execute)

    for _i, (_trg, _rep) in enumerate(PROGRAMMING_CONCEPTS):
        _cb_register_concept(_i, _trg, _rep)
