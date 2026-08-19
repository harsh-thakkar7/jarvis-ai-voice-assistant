
    # ---- F. APP DEVELOPMENT ----------------------------------------------

    APP_KB = [
        (("android activity lifecycle", "activity lifecycle android"),
         "Activity lifecycle callbacks, sir:\nonCreate -> onStart -> onResume"
         " -> [running] -> onPause -> onStop -> onDestroy.\nSave state in "
         "onSaveInstanceState; release resources in onStop/onDestroy."),
        (("android intent",),
         'Intents start actions, sir:\nExplicit: Intent(this, DetailActivity::'
         'class.java)\nImplicit: Intent(Intent.ACTION_SEND).apply { type = '
         '"text/plain"; putExtra(Intent.EXTRA_TEXT, msg) }\nstartActivity('
         "intent) launches it."),
        (("jetpack compose",),
         "Jetpack Compose builds UI in Kotlin, sir:\n@Composable\nfun Counter()"
         ' {\n  var count by remember { mutableStateOf(0) }\n  Button(onClick ='
         ' { count++ }) { Text("Count: $count") }\n}\nRecomposition redraws on '
         "state change."),
        (("recyclerview", "android list view"),
         "RecyclerView renders long lists efficiently, sir: adapter binds "
         "viewholders, LayoutManager positions them, DiffUtil updates only "
         "changed rows. In Compose, LazyColumn replaces it entirely."),
        (("android room database", "room database"),
         'Room persists SQLite via annotations, sir:\n@Entity data class User('
         '@PrimaryKey val id: Int, val name: String)\n@Dao interface UserDao { '
         '@Query("SELECT * FROM User") fun all(): Flow<List<User>> }\n@Database('
         "entities=[User::class]) abstract class AppDb : RoomDatabase()"),
        (("retrofit android",),
         "Retrofit types HTTP APIs, sir:\ninterface Api { @GET(\"users/{id}\") "
         "suspend fun user(@Path(\"id\") id: Int): User }\nRetrofit.Builder()."
         'baseUrl("https://x.dev/").addConverterFactory(MoshiConverterFactory.'
         "create()).build().create(Api::class.java)"),
        (("android gradle", "gradle dependencies android"),
         "Gradle manages Android builds, sir: app/build.gradle.kts lists "
         'dependencies { implementation("com.squareup.retrofit2:retrofit:'
         '2.11.0") }. Sync after edits; buildTypes switch debug/release flags.'),
        (("android permissions", "android manifest"),
         'Android permissions go in the manifest, sir:\n<uses-permission '
         'android:name="android.permission.INTERNET"/>\nDangerous ones (camera,'
         " location) also need runtime requestPermissions() on API 23+."),
        (("android fragment",),
         "Fragments are reusable UI sections inside activities, sir: own "
         "lifecycle tied to the host, swapped via FragmentManager, sharing "
         "ViewModels with the activity. Compose Navigation largely replaces "
         "them in new apps."),
        (("swiftui view", "swiftui basics"),
         "SwiftUI declares views, sir:\nstruct Counter: View {\n  @State private"
         ' var count = 0\n  var body: some View {\n    Button("Count: \\(count)")'
         " { count += 1 }\n  }\n}\nBody recomputes when @State changes."),
        (("swiftui state wrappers", "binding swiftui"),
         "SwiftUI property wrappers, sir: @State for local value, @Binding to "
         "share write access, @StateObject/@ObservedObject for reference models,"
         " @EnvironmentObject for app-wide injection."),
        (("uikit view controller", "view controller lifecycle ios"),
         "UIKit lifecycle order, sir: viewDidLoad (once, wire UI) -> "
         "viewWillAppear -> viewDidAppear -> viewWillDisappear -> "
         "viewDidDisappear. Auto Layout constraints set geometry; outlets connect"
         " storyboard views to code."),
        (("swift optionals", "swift language basics"),
         "Swift optionals ban nil accidents, sir:\nvar name: String? = nil\nif let"
         ' n = name { print(n) }        // safe unwrap\nguard let n = name else { '
         'return }   // early exit\nlet n2 = name ?? "guest"    // default'),
        (("uitableview", "ios table view"),
         "UITableView lists data via datasource/delegate, sir: numberOfRowsInSection"
         " + cellForRowAt dequeue cells. SwiftUI List(rows) achieves the same "
         "declaratively with swipe actions for free."),
        (("core data ios",),
         "Core Data persists object graphs, sir: model entities in the .xcdatamodeld"
         " editor, NSPersistentContainer loads the store, NSFetchRequest queries, "
         "@FetchRequest integrates SwiftUI views directly."),
        (("app store submission", "publish ios app"),
         "Ship to the App Store, sir: Apple Developer account ($99/yr) -> archive"
         " a release build in Xcode -> upload via Transporter -> fill App Store "
         "Connect listing (screenshots, privacy labels) -> submit for review "
         "(usually 24-48h)."),
        (("google play publish", "publish android app"),
         "Publish to Google Play, sir: Play Console account ($25 once) -> generate"
         " a signed AAB in Android Studio -> create listing with screenshots and "
         "content rating -> roll out to internal, then closed, then production "
         "tracks."),
        (("react native setup",),
         "React Native ships JS mobile apps, sir: npx create-expo-app MyApp -> "
         "npx expo start gives QR-code previews. Views map to native widgets; most"
         " npm React knowledge transfers."),
        (("react native styling", "react native components"),
         "RN styles with StyleSheet, sir:\nimport { View, Text, StyleSheet } from"
         " 'react-native';\n<View style={styles.box}><Text>Hello</Text></View>\nconst"
         " styles = StyleSheet.create({ box: { flex: 1, justifyContent: 'center' } });"),
        (("react native navigation",),
         "Navigation in RN, sir: @react-navigation/native provides Stack (push/pop),"
         " Tab, and Drawer navigators.\nnavigation.navigate('Details', { id: 7 }) "
         "pushes; route.params reads the payload."),
        (("flutter setup", "flutter create app"),
         "Flutter setup, sir: install SDK + Android Studio plugin -> flutter doctor"
         " verifies toolchain -> flutter create my_app -> flutter run. Hot reload "
         "applies edits in under a second."),
        (("flutter widget", "stateful widget flutter"),
         "Flutter is widgets all the way down, sir:\nclass Hello extends "
         "StatelessWidget {\n  Widget build(BuildContext c) => Text('Hi');\n}\nExtend"
         " StatefulWidget when data changes; setState() triggers rebuild."),
        (("flutter navigation", "flutter routes"),
         "Flutter navigation, sir:\nNavigator.push(context, MaterialPageRoute("
         "builder: (_) => DetailPage()));\nNavigator.pop(context);\nNamed routes: "
         "MaterialApp(routes: {'/detail': (_) => DetailPage()}), then pushNamed('/"
         "detail')."),
        (("flutter http",),
         "Flutter HTTP, sir: add package:http ->\nfinal res = await http.get(Uri.parse(url));"
         "\nif (res.statusCode == 200) { final data = jsonDecode(res.body); }\nWrap in"
         " FutureBuilder or use async state management (Riverpod/Bloc)."),
        (("dart null safety", "dart basics"),
         "Dart is typed with null safety, sir:\nString? nickname;   // may be null\n"
         "nickname?.length       // null-aware call\nnickname ?? 'none'    // default"
         "\nlate String forced;   // set before use, trust me"),
        (("mvvm architecture", "mvvm pattern"),
         "MVVM splits Model (data), View (passive UI), ViewModel (state + logic "
         "exposed observably). Views bind to ViewModel properties - testable logic,"
         " thin screens. Standard on WPF, Android, and SwiftUI with Combine."),
        (("mvc vs mvp vs mvvm", "mvc mvp mvvm"),
         "UI pattern spectrum, sir: MVC wires a controller between view and model;"
         " MVP inserts a presenter the view talks to (testable, chatty); MVVM lets"
         " the view observe a viewmodel declaratively. Modern UI kits favor MVVM-ish"
         " binding."),
        (("push notifications fcm", "apns push"),
         "Push notifications ride FCM (Android) or APNs (iOS), sir: app gets a device"
         " token, your server sends payloads through the service, OS displays them."
         " FlutterFire/Notifee or UNUserNotificationCenter handle the client side."),
        (("mobile local storage", "shared preferences android"),
         "Mobile persistence menu, sir: SharedPreferences/UserDefaults for tiny "
         "key-value flags; SQLite/Room/Core Data for structured data; files for blobs;"
         " Keychain/Keystore for secrets - never plain storage."),
        (("deep linking mobile", "universal links"),
         "Deep links open app screens from URLs, sir: register a scheme or universal"
         " link/domain association, route by path (products/42), fall back to web when"
         " the app is missing. Great for campaigns and sharing."),
        (("mobile app security",),
         "Mobile security checklist, sir: TLS everywhere + certificate pinning, tokens"
         " in Keychain/Keystore, no secrets in code, biometric gates for sensitive "
         "screens, obfuscate (ProGuard/R8), and validate server-side - never trust the"
         " client."),
        (("responsive mobile layout", "handle screen sizes"),
         "Handle screen diversity, sir: constraint/rule-based layouts over magic "
         "numbers, size classes/window breakpoints for tablets, scalable fonts, safe"
         " areas (notches), and test on small + big + foldable previews."),
        (("electron app setup", "build desktop app electron"),
         "Electron wraps Chromium + Node for desktop apps, sir:\nnpm i electron\nmain.js"
         " creates BrowserWindow loading index.html; the page is your renderer. VS Code"
         " and Slack ship this way."),
        (("electron ipc",),
         "Electron IPC bridges processes, sir:\npreload.js: contextBridge."
         "exposeInMainWorld('api', { save: d => ipcRenderer.invoke('save', d) })\nmain.js:"
         " ipcMain.handle('save', (e, d) => fs.write(...))\nRenderer calls window.api.save(data)."),
        (("electron packaging", "package electron app"),
         "Package Electron apps, sir: electron-builder or Forge bundle installers - npx"
         " electron-builder --mac --win --linux produces .dmg/.exe/AppImage. Code-sign"
         " with developer certificates for smooth installs."),
        (("tkinter window", "tkinter hello world"),
         "Tkinter window, sir:\nimport tkinter as tk\nroot = tk.Tk()\nroot.title('App')"
         "\ntk.Label(root, text='Hello').pack(padx=20, pady=10)\nroot.mainloop()"),
        (("tkinter button widget", "tkinter events"),
         "Tkinter widgets respond via command or bind, sir:\nbtn = tk.Button(root, "
         "text='Go', command=on_go)\nentry.bind('<Return>', lambda e: submit())\nWidgets:"
         " Label, Entry, Text, Listbox, Canvas, plus ttk themed variants."),
        (("tkinter grid layout", "tkinter layout"),
         "Tkinter geometry managers, sir: grid(row=, column=) for tables, pack(side=)"
         " for edges, place(x=, y=) for absolute. Mixing managers in one container "
         "misbehaves - pick grid for real forms."),
        (("tkinter dialog", "tkinter file dialog", "messagebox tkinter"),
         "Tkinter dialogs, sir:\nfrom tkinter import filedialog, messagebox\npath = "
         "filedialog.askopenfilename()\nmessagebox.showinfo('Done', 'Saved successfully')"
         "\nasksaveasfilename and showerror round it out."),
        (("pyqt python gui", "pyside qt"),
         "PyQt/PySide wrap Qt, sir:\nfrom PySide6.QtWidgets import QApplication, QLabel"
         "\napp = QApplication([])\nQLabel('Hello').show()\napp.exec()\nQt Designer drags"
         " UIs; pyuic/pyside-uic convert them to Python."),
        (("signals and slots", "pyqt signals"),
         "Signals and slots wire Qt events, sir:\nbtn.clicked.connect(self.on_click)"
         "\ncustom = Signal(str)  # declare in QObject class\ncustom.emit('done')  # anyone"
         " listening reacts\nLoose coupling, thread-safe delivery."),
        (("kivy python mobile",),
         "Kivy builds touch apps in pure Python, sir:\nfrom kivy.app import App\nfrom "
         "kivy.uix.button import Button\nclass MyApp(App):\n    def build(self): return"
         " Button(text='Tap me')\nMyApp().run()\nBuildozer packages to Android."),
        (("wxpython",),
         "wxPython gives native-looking desktop UIs, sir:\nimport wx\napp = wx.App()\nf ="
         " wx.Frame(None, title='App')\nf.Show()\napp.MainLoop()\nSizers manage layout;"
         " events bind with Bind()."),
        (("tauri desktop app",),
         "Tauri builds tiny desktop apps: Rust core + system webview instead of bundled"
         " Chromium, sir - megabytes not hundreds. Frontend stays any JS framework; src-tauri/"
         " commands expose native power."),
        (("menubar tray app", "system tray application"),
         "Menu bar/tray apps live beside the clock, sir: macOS NSStatusItem (or rumps for"
         " Python), Windows tray icon via pystray, Electron Tray class. Perfect for monitors"
         " and quick actions - no dock clutter."),
        (("progressive web app", "pwa"),
         "PWAs install web apps to home screens, sir: web app manifest (name, icons), service"
         " worker caching shell + data, HTTPS, offline page. Lighthouse audits installability."),
        (("capacitor cordova", "wrap web app mobile"),
         "Capacitor/Cordova wrap web apps in native shells, sir: npm i @capacitor/core "
         "@capacitor/cli -> npx cap add ios android -> native plugins expose camera/files/"
         "geolocation to JS."),
        (("mobile app testing",),
         "Mobile testing pyramid, sir: unit tests for logic (JUnit/XCTest/pytest), integration"
         " for repos/APIs, UI automation (Espresso, XCUITest, Appium, Maestro) on real devices,"
         " plus Firebase Test Lab farms."),
        (("app monetization",),
         "Monetization models, sir: paid upfront (simple, high friction), freemium + IAP "
         "upgrades, subscriptions for ongoing value, ads (AdMob banners/interstitials/rewarded),"
         " hybrid. Store fees run 15-30%."),
        (("sqlite mobile app",),
         "SQLite is the embedded workhorse, sir: zero-config single-file DB inside the app."
         " Python: import sqlite3; conn.execute('CREATE TABLE ...'). Mobile equivalents: Room"
         " (Android), Core Data/GRDB (iOS)."),
        (("android viewmodel", "viewmodel livedata"),
         "ViewModel survives rotation and holds UI state, sir:\nclass MainVm : ViewModel() {"
         "\n  private val _count = MutableLiveData(0)\n  val count: LiveData<Int> get() = _count"
         "\n  fun inc() { _count.value = (_count.value ?: 0) + 1 }\n}\nObserve from the activity;"
         " StateFlow is the modern flavor."),
    ]

    for _i, (_trg, _rep) in enumerate(APP_KB):
        _cb_kb("cb_app", _i, _trg, _rep)
