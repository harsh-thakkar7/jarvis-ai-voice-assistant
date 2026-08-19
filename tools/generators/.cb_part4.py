
    # ---- E-H. KNOWLEDGE BASE REGISTRAR -----------------------------------

    def _cb_kb(prefix, idx, triggers, reply):
        alts = "|".join(re.escape(t) for t in triggers)
        pat = re.compile(
            r"(?:\b(?:what\s+is|what's|whats|explain|define|tell\s+me\s+"
            r"about|how\s+(?:do|does|to|can|would)(?:\s+i|\s+you|\s+we|\s+"
            r"one)?|show\s+me|teach\s+me)\s+(?:a\s+|an\s+|the\s+|some\s+|"
            r"about\s+)?(?:%s)s?\b"
            r"|\b(?:%s)s?\s+(?:example|examples|tutorial|boilerplate|"
            r"cheat\s?sheet)\b)" % (alts, alts), re.I)

        def detect(cmd, _pat=pat):
            if _pat.search(cmd):
                return {"cmd": cmd}
            return None

        def execute(app, cmd, _reply=reply):
            return _reply

        brain.reg_fn("%s_%03d" % (prefix, idx), detect, execute)

    # ---- E. WEB DEVELOPMENT ----------------------------------------------

    WEB_KB = [
        (("html boilerplate", "basic html page", "html skeleton"),
         'HTML5 boilerplate, sir:\n<!DOCTYPE html>\n<html lang="en">\n'
         "<head>\n"
         '  <meta charset="UTF-8">\n'
         '  <meta name="viewport" content="width=device-width, '
         'initial-scale=1.0">\n  <title>Page</title>\n</head>\n<body>\n'
         "  <h1>Hello</h1>\n</body>\n</html>"),
        (("semantic html", "semantic tags"),
         "Semantic tags describe meaning: <header>, <nav>, <main>, "
         "<article>, <section>, <aside>, <footer>. Screen readers and SEO "
         "both love them over div soup, sir."),
        (("viewport meta",),
         'Responsive pages start with: <meta name="viewport" '
         'content="width=device-width, initial-scale=1.0"> - it maps CSS '
         "pixels to device width instead of zooming out, sir."),
        (("css flexbox", "flexbox"),
         "Flexbox aligns children along one axis, sir:\n.container {\n"
         "  display: flex;\n  justify-content: space-between;\n"
         "  align-items: center;\n  gap: 16px;\n}"),
        (("css grid", "grid layout"),
         "CSS Grid handles two dimensions, sir:\n.grid {\n  display: grid;"
         "\n  grid-template-columns: repeat(3, 1fr);\n  gap: 20px;\n}\n"
         "Place children with grid-column/grid-row spans."),
        (("center a div", "center div"),
         "Three modern ways to center a div, sir:\n1. display:flex + "
         "align-items:center + justify-content:center on the parent.\n2. "
         "display:grid + place-items:center.\n3. position:absolute; top:50%;"
         " left:50%; transform:translate(-50%, -50%)."),
        (("media query", "media queries"),
         "Media queries adapt styles to screens, sir:\n@media "
         "(max-width: 600px) {\n  .sidebar { display: none; }\n}\n"
         "Mobile-first: default styles for phones, min-width queries upward."),
        (("css variables", "custom properties"),
         "CSS variables cascade and update at runtime, sir:\n:root { "
         "--brand: #00d4ff; }\n.button { background: var(--brand); }\nJS can"
         " flip themes via element.style.setProperty."),
        (("css transition", "hover effect"),
         "Transitions animate state changes smoothly, sir:\n.button { "
         "transition: transform .2s ease, background .2s; }\n.button:hover {"
         " transform: translateY(-2px); background: #09c; }"),
        (("css animation", "keyframes css"),
         "Keyframes animate without JS, sir:\n@keyframes pulse {\n  50% { "
         "opacity: .5; }\n}\n.badge { animation: pulse 1.5s infinite; }"),
        (("responsive image", "responsive images"),
         'Responsive images ship the right size, sir:\n<img src="small.jpg"'
         '\n     srcset="large.jpg 1200w, small.jpg 600w"\n     sizes='
         '"(max-width: 600px) 100vw, 50vw">'),
        (("tailwind", "tailwind css"),
         'Tailwind styles via utility classes, sir:\n<button class="bg-'
         'blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">'
         "Click</button>\nConfigure theme in tailwind.config.js."),
        (("bootstrap",),
         'Bootstrap gives a grid and components, sir:\n<div class="row">\n'
         '  <div class="col-md-6">Left</div>\n  <div class="col-md-6">'
         "Right</div>\n</div>\nPlus ready-made buttons, modals, navbars."),
        (("sass", "scss"),
         "Sass adds nesting, variables, and mixins to CSS, sir:\n$brand: "
         "#09c;\n.card {\n  color: $brand;\n  &:hover { opacity: .8; }\n}\n"
         "Compiles to plain CSS."),
        (("react component", "functional component react"),
         "React functional component, sir:\nfunction Greet({ name }) {\n"
         "  return <h1>Hello, {name}</h1>;\n}\nUse <Greet name=\"Sam\" /> - "
         "JSX compiles to React.createElement calls."),
        (("react props",),
         "Props flow down into components, sir:\n<Card title=\"Hi\" />\n"
         "function Card({ title }) { return <h2>{title}</h2>; } They are "
         "read-only; state changes come from the owner, sir."),
        (("react state", "usestate", "use state"),
         "useState holds changing values, sir:\nconst [count, setCount] = "
         "useState(0);\n<button onClick={() => setCount(count + 1)}>{count}"
         "</button>\nSetting state re-renders the component."),
        (("useeffect", "use effect", "react effect"),
         "useEffect runs side effects after render, sir:\nuseEffect(() => {"
         "\n  fetch('/api/data').then(r => r.json()).then(setData);\n}, []);"
         "\nThe [] deps array means once; add dependencies to re-run."),
        (("conditional rendering",),
         "React renders conditionally with JS operators, sir:\n{isLoggedIn ?"
         " <Dashboard /> : <Login />}\n{errors.length > 0 && <Alert "
         "msgs={errors} />}"),
        (("react list render", "keys react"),
         "Render lists with map and stable keys, sir:\n{todos.map(t => <li "
         "key={t.id}>{t.text}</li>)}\nKeys let React track identity across "
         "re-renders."),
        (("react form", "controlled input"),
         "Controlled forms bind inputs to state, sir:\nconst [email, setEmail]"
         " = useState('');\n<input value={email} onChange={e => setEmail(e."
         "target.value)} />"),
        (("react context", "context api"),
         "Context passes data down without prop drilling, sir:\nconst "
         "ThemeCtx = createContext('light');\n<ThemeCtx.Provider value=\"dark"
         "\">...</ThemeCtx.Provider>\nconst theme = useContext(ThemeCtx);"),
        (("custom hook", "custom hooks"),
         "Custom hooks reuse stateful logic, sir:\nfunction useFetch(url) {\n"
         "  const [data, setData] = useState(null);\n  useEffect(() => { "
         "fetch(url).then(r => r.json()).then(setData); }, [url]);\n  return"
         " data;\n}"),
        (("redux",),
         "Redux keeps app state in one store; dispatch actions, reducers "
         "return new state, sir:\ndispatch({ type: 'counter/increment' })\n"
         "Modern Redux Toolkit slices cut the boilerplate massively."),
        (("react router",),
         'React Router maps URLs to components, sir:\n<Routes>\n  <Route '
         'path="/" element={<Home />} />\n  <Route path="/user/:id" element='
         "{<User />} />\n</Routes>\nuseNavigate() moves programmatically."),
        (("next js", "nextjs"),
         "Next.js adds file-based routing, SSR, and API routes to React, "
         "sir:\npages/index.js -> /\npages/posts/[id].js -> /posts/1\n"
         "getServerSideProps fetches data per request."),
        (("vue component", "vue js"),
         "Vue components combine template, script, style, sir:\n<script setup>"
         "\nimport { ref } from 'vue';\nconst count = ref(0);\n</script>\n"
         '<template><button @click="count++">{{ count }}</button></template>'),
        (("angular component", "angular framework"),
         "Angular organizes by modules, components, services, sir:\n@"
         "Component({ selector: 'app-hello', template: '<h1>{{title}}</h1>' })"
         "\nexport class HelloComponent { title = 'Angular'; }\nData flows "
         "via @Input(), events via @Output()."),
        (("svelte",),
         "Svelte compiles away the framework, sir:\n<script>let count = 0;"
         "</script>\n<button on:click={() => count++}>{count}</button>\n"
         "Reactivity is plain assignment - no hooks or refs."),
        (("dom manipulation",),
         "DOM manipulation with vanilla JS, sir:\ndocument.querySelector("
         "'#box').textContent = 'Hi';\nel.classList.add('active');\nel."
         "setAttribute('href', url);\nparent.appendChild(node);"),
        (("addeventlistener", "event listener javascript"),
         "Event listeners wire interactions, sir:\nbtn.addEventListener('click'"
         ", (e) => { e.preventDefault(); submit(); });\nremoveEventListener "
         "cleans up on teardown."),
        (("fetch api", "fetch javascript"),
         "Fetch calls APIs, sir:\nconst res = await fetch('/api/users', { "
         "method: 'POST', headers: {'Content-Type': 'application/json'}, body:"
         " JSON.stringify(user) });\nif (!res.ok) throw new Error(res.status);"),
        (("async function javascript",),
         "Async/await flattens promise chains, sir:\nasync function load() {\n"
         "  try {\n    const res = await fetch(url);\n    return await res.json();"
         "\n  } catch (e) { console.error(e); }\n}"),
        (("promises javascript", "promise chain"),
         "Promises chain async steps, sir:\nfetch(url)\n  .then(r => r.json())"
         "\n  .then(data => render(data))\n  .catch(err => console.error(err));"
         "\nPromise.all waits for many at once."),
        (("arrow function", "arrow functions"),
         "Arrow functions are concise and inherit 'this', sir:\nconst add = "
         "(a, b) => a + b;\nsetTimeout(() => this.save(), 100);\nAvoid them as"
         " object methods needing their own this."),
        (("destructuring javascript", "spread operator"),
         "Destructuring unpacks, spread copies, sir:\nconst { name, age } = "
         "user;\nconst [first, ...rest] = list;\nconst merged = { ...defs, ..."
         "overrides };\nCopy arrays with [...arr]."),
        (("template literal", "template literals"),
         "Template literals interpolate and span lines, sir:\n`Hello ${name},"
         " you have ${count} messages.`\nExpressions go inside ${ }, including"
         " function calls."),
        (("array methods javascript", "map filter reduce"),
         "Array trinity, sir:\nxs.map(x => x * 2)      // transform\nxs.filter(x"
         " => x.ok)    // select\nxs.reduce((sum, x) => sum + x, 0) // fold\nThey"
         " return new arrays/values - chainable and pure."),
        (("localstorage", "local storage javascript"),
         "localStorage persists strings across sessions; sessionStorage clears"
         " with the tab, sir:\nlocalStorage.setItem('theme', 'dark');\nconst t ="
         " localStorage.getItem('theme');\nStore JSON via JSON.stringify/parse."),
        (("form validation javascript",),
         "Validate forms on submit and on blur, sir:\nform.addEventListener("
         "'submit', e => {\n  if (!email.includes('@')) { e.preventDefault(); "
         "showError(); }\n});\nHTML5 helpers: required, type=email, pattern."),
        (("rest api design", "api design best practices"),
         "REST design rules, sir:\nNouns for URLs (/users/42/orders), verbs via"
         " HTTP methods, plural collections, filtering via query ?status=open,"
         " version /v1/, meaningful status codes (201 created, 400 bad input,"
         " 404 missing)."),
        (("http status codes", "status codes http"),
         "Status code families, sir:\n200 OK, 201 Created, 204 No Content\n"
         "301/308 redirect, 304 cached\n400 bad input, 401 unauthenticated, 403"
         " forbidden, 404 missing, 409 conflict, 422 invalid\n500 server bug, "
         "502 upstream, 503 unavailable, 429 rate limited."),
        (("http methods",),
         "HTTP verbs carry semantics, sir:\nGET reads (safe, cacheable), POST "
         "creates, PUT replaces fully, PATCH updates partly, DELETE removes. "
         "Idempotent: GET/PUT/PATCH/DELETE - safe to retry."),
        (("jwt authentication", "jwt token"),
         "JWT auth flow, sir:\n1. Login -> server signs token (header.payload."
         "signature).\n2. Client sends Authorization: Bearer <token>.\n3. Server"
         " verifies signature, no session store needed.\nKeep tokens short-lived;"
         " refresh tokens renew."),
        (("oauth flow", "oauth2"),
         "OAuth2 delegates access without sharing passwords, sir: your app "
         "redirects to Google, the user consents, Google returns a code, your "
         "backend exchanges it for tokens. PKCE protects public clients."),
        (("websocket javascript", "socket io"),
         "Real-time channels with WebSockets, sir:\nconst ws = new WebSocket("
         "'ws://host');\nws.onmessage = e => render(JSON.parse(e.data));\nws.send"
         "(JSON.stringify(msg));\nSocket.IO adds rooms and fallbacks."),
        (("flask app", "flask hello world"),
         "Minimal Flask app, sir:\nfrom flask import Flask\napp = Flask(__name__)"
         "\n\n@app.route('/')\ndef home():\n    return 'Hello!'\n\napp.run(debug="
         "True)\nRoutes with vars: @app.route('/user/<name>')"),
        (("flask blueprint", "blueprints flask"),
         "Blueprints split Flask apps, sir:\nusers_bp = Blueprint('users', "
         "__name__, url_prefix='/users')\n@users_bp.route('/')\ndef list_(): ..."
         "\napp.register_blueprint(users_bp)"),
        (("django setup", "start django project"),
         "Start Django, sir:\npip install django\ndjango-admin startproject "
         "mysite\ncd mysite && python manage.py startapp blog\npython manage.py "
         "migrate\npython manage.py runserver"),
        (("django model", "django views"),
         "Django MVT, sir:\nmodels.py: class Post(models.Model): title = models."
         "CharField(max_length=200)\nviews.py: def index(request): return render("
         "request, 'index.html', {'posts': Post.objects.all()})\nurls.py maps "
         "paths to views."),
        (("express server", "express js hello"),
         "Express server, sir:\nconst express = require('express');\nconst app ="
         " express();\napp.use(express.json());\napp.get('/hello', (req, res) =>"
         " res.json({ hi: true }));\napp.listen(3000);"),
        (("express middleware",),
         "Middleware runs before handlers, sir:\napp.use((req, res, next) => { "
         "console.log(req.method, req.url); next(); });\nAuth checks, body "
         "parsing, logging all live here; errors take (err, req, res, next)."),
        (("fastapi app",),
         "FastAPI serves typed async APIs, sir:\nfrom fastapi import FastAPI\n"
         "app = FastAPI()\n\n@app.get('/items/{item_id}')\nasync def read(item_id:"
         ' int, q: str | None = None):\n    return {"item_id": item_id, "q": q}'
         "\nAuto docs at /docs, sir."),
        (("npm commands",),
         "npm essentials, sir:\nnpm init -y        # package.json\nnpm install "
         "express  # add dependency\nnpm install -D jest   # dev dependency\nnpm"
         " run dev        # run scripts\nnpx create-vite app # scaffold without "
         "installing"),
        (("webpack vite", "bundler javascript"),
         "Bundlers pack modules for the browser, sir: Vite dev-runs with instant"
         " HMR (npm create vite@latest), production-builds optimized assets. "
         "Webpack configures loaders/plugins; most scaffolds hide it nowadays."),
        (("sql join", "joins sql"),
         "SQL joins, sir:\nINNER JOIN keeps matches only; LEFT JOIN keeps all "
         "left rows (NULL where missing); RIGHT mirrors it; FULL keeps everything;"
         " CROSS multiplies.\nSELECT u.name, COUNT(o.id) FROM users u LEFT JOIN "
         "orders o ON o.user_id = u.id GROUP BY u.id;"),
        (("sql create index", "index sql table"),
         "Speed up filters with indexes, sir:\nCREATE INDEX idx_users_email ON "
         "users(email);\nComposite order matters (email, created_at). Check usage"
         " with EXPLAIN QUERY PLAN before and after."),
        (("mongodb crud", "mongo db basics"),
         "MongoDB CRUD, sir:\ndb.users.insertOne({ name: 'Ada' })\ndb.users.find({"
         " age: { $gt: 21 } })\ndb.users.updateOne({ name: 'Ada' }, { $set: { age:"
         " 37 } })\ndb.users.deleteOne({ name: 'Ada' })"),
        (("mongoose schema",),
         "Mongoose models MongoDB documents, sir:\nconst User = mongoose.model("
         "'User', new mongoose.Schema({\n  name: { type: String, required: true },"
         "\n  age: Number\n}));\nawait User.create({ name: 'Ada' });"),
        (("sql vs nosql",),
         "Choose SQL for relationships, strict schema, and ACID money math; choose"
         " NoSQL for flexible documents, horizontal scale, and cache-like speed. "
         "Most real systems happily use both, sir."),
    ]

    for _i, (_trg, _rep) in enumerate(WEB_KB):
        _cb_kb("cb_web", _i, _trg, _rep)
