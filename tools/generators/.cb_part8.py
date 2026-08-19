
    # ---- H. SYSTEM PROGRAMMING --------------------------------------------

    SYS_KB = [
        (("bash script basics", "shell script shebang"),
         "Shell scripts start with a shebang, sir:\n#!/usr/bin/env bash\nset -euo pipefail   # fail fast, unset"
         " vars, pipeline errors\necho 'hello'\nchmod +x script.sh && ./script.sh"),
        (("bash script arguments",),
         'Script arguments, sir:\n$1 $2 ... positional; $# count; $@ all quoted; $? last exit code\nfirst="$1"'
         "\n[ $# -lt 1 ] && { echo 'usage: ...'; exit 1; }"),
        (("bash if statement", "bash conditionals"),
         'Bash conditionals, sir:\nif [[ -f "$file" ]]; then\n  echo exists\nelif [[ -z "$name" ]]; then\n'
         "  echo empty\nelse\n  echo other\nfi\nTests: -d dir, -e exists, -x executable, == glob match."),
        (("bash for loop", "while loop bash"),
         'Bash loops, sir:\nfor f in *.txt; do echo "$f"; done\nfor i in $(seq 1 5); do ... \nwhile read -r line;'
         ' do echo "$line"; done < file.txt\nC-style: for ((i=0; i<5; i++)).'),
        (("bash functions",),
         'Bash functions, sir:\ngreet() {\n  local name="$1"\n  echo "hi $name"\n}\ngreet Sam   # prints: hi Sam'
         "\nReturn codes with 'return N'; echo for output capture."),
        (("cron job schedule", "crontab format"),
         "Schedule with cron, sir: crontab -e then:\n0 9 * * * /path/job.sh  # daily 9am\n*/5 * * * * cmd       "
         "# every 5 min\nFormat: minute hour day month weekday. Log with >> log 2>&1."),
        (("environment variables export", "export environment variable"),
         "Environment variables, sir:\nexport API_KEY=secret   # children inherit\nprintenv | grep PATH\necho "
         '"$HOME"\nPersist in ~/.zshrc or ~/.bashrc; .env files feed dotenv loaders.'),
        (("chmod permissions", "file permissions linux"),
         "Unix permissions, sir:\nchmod 755 script.sh   # rwxr-xr-x\nchmod +x file             # add execute\n"
         "chown user:group file\nDigits: r=4 w=2 x=1 summed per owner/group/other."),
        (("systemd service unit", "systemctl commands"),
         "systemd services, sir:\n/etc/systemd/system/app.service:\n[Unit]\nDescription=App\n[Service]\n"
         "ExecStart=/usr/bin/python /opt/app.py\nRestart=always\n[Install]\nWantedBy=multi-user.target\nsudo "
         "systemctl enable --now app"),
        (("launchd macos plist", "macos launch agent"),
         "macOS scheduling via launchd, sir: drop a plist in ~/Library/LaunchAgents/com.me.job.plist with "
         "ProgramArguments + StartCalendarInterval, then launchctl load that path. Replaces cron for GUI-adjacent jobs."),
        (("makefile basics", "write makefile"),
         "Makefiles automate builds, sir:\n.PHONY: test lint\ntest:\n\tpytest -q\nlint:\n\truff check .\ninstall:"
         "\n\tpip install -r requirements.txt\nRun 'make test'; recipes need TAB indent."),
        (("cmake build system",),
         "CMake generates native builds, sir:\ncmake_minimum_required(VERSION 3.20)\nproject(App)\nadd_executable(app main.cpp util.cpp)"
         "\nBuild: cmake -B build && cmake --build build"),
        (("ssh key setup", "connect ssh server"),
         "SSH keys replace passwords, sir:\nssh-keygen -t ed25519\nssh-copy-id user@server\nssh -p 2222 user@server"
         "\nConfig shortcuts in ~/.ssh/config: Host prod / HostName x / User y."),
        (("scp rsync transfer files",),
         "Move files remotely, sir:\nscp file.zip user@host:/tmp/\nrsync -avz --delete src/ user@host:/dst/   # resumes, syncs deltas"
         "\n-n dry-run first, always."),
        (("nginx reverse proxy", "nginx config file"),
         "Nginx reverse proxy, sir:\nserver {\n  listen 80;\n  location / {\n    proxy_pass http://127.0.0.1:8000;"
         "\n    proxy_set_header Host $host;\n  }\n}\nsudo nginx -t validates; reload with systemctl."),
        (("write dockerfile", "dockerfile example"),
         'Dockerfile recipe, sir:\nFROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install '
         '-r requirements.txt\nCOPY . .\nCMD ["python", "app.py"]\ndocker build -t app . && docker run -p 8000:8000 app'),
        (("docker compose file", "docker-compose yaml"),
         'Compose orchestrates multi-container stacks, sir:\nservices:\n  web:\n    build: .\n    ports: ["8000:8000"]'
         "\n  db:\n    image: postgres:16\n    environment:\n      POSTGRES_PASSWORD: secret\ndocker compose up -d"),
        (("docker volumes networks",),
         "Docker persistence + networking, sir:\nvolumes: dbdata -> mounts survive rebuilds\ndocker run -v $(pwd)/src:/app/src dev"
         "  # bind mount\nServices on one compose network reach each other by name: postgres://db:5432."),
        (("github actions workflow", "github ci pipeline"),
         "GitHub Actions CI, sir: .github/workflows/ci.yml\nname: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest"
         "\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        "
         "with: { python-version: '3.12' }\n      - run: pip install -r requirements.txt && pytest"),
        (("gitlab ci pipeline",),
         "GitLab CI, sir: .gitlab-ci.yml at repo root\nstages: [test, deploy]\ntest:\n  stage: test\n  image: python:3.12"
         "\n  script:\n    - pip install -r requirements.txt\n    - pytest\nRunners execute jobs; artifacts pass outputs downstream."),
        (("jenkinsfile pipeline", "jenkins pipeline as code"),
         "Jenkins pipelines as code, sir:\npipeline {\n  agent any\n  stages {\n    stage('Test') { steps { sh 'pytest -q' } }"
         "\n    stage('Deploy') { steps { sh './deploy.sh' } }\n  }\n}\nCommit alongside the repo."),
        (("git branch strategy", "git branching workflow"),
         "Branch workflows, sir:\ngit switch -c feature/login  # create+switch\ngit merge feature/login   # onto target"
         "\ngit branch -d old-stuff     # delete\nConvention: feature/, fix/, release/ prefixes keep history readable."),
        (("git rebase vs merge", "interactive rebase"),
         "Rebase replays commits onto a new base for linear history, sir:\ngit fetch origin\ngit rebase origin/main"
         "\nInteractive cleanup: git rebase -i HEAD~5 (squash/reword/drop). Golden rule: never rewrite shared branches."),
        (("git tags release", "git tag version"),
         "Tag releases, sir:\ngit tag -a v1.4.0 -m 'Stable release'\ngit push origin v1.4.0\nSemantic versioning: "
         "MAJOR.MINOR.PATCH; CI often builds artifacts from tags."),
        (("gitignore file",),
         ".gitignore keeps noise out of history, sir:\n__pycache__/\n*.pyc\nnode_modules/\n.env\n.DS_Store\ndebug.log"
         "\nAlready-tracked files ignore late - untrack them first with git rm --cached."),
        (("git bisect find bug",),
         "git bisect hunts regressions, sir:\ngit bisect start\ngit bisect bad          # current commit broken"
         "\ngit bisect good v1.2.0 # known good tag\nMark each step good/bad; ~10 steps finds the culprit in thousands of commits."),
        (("linux processes top kill",),
         "Process management, sir:\ntop or htop to watch\tps aux | grep python to list\nkill 1234 polite, kill -9 1234 force"
         "\npkill -f app.py by name\nnice -n 10 cmd lowers priority."),
        (("journalctl logs linux", "check service logs"),
         "Service logs via journalctl, sir:\njournalctl -u nginx -f          # follow one unit\njournalctl --since '1 hour ago'"
         "\njournalctl -p err -b              # this boot's errors\nPlain files live in /var/log/; tail -f follows them."),
    ]

    for _i, (_trg, _rep) in enumerate(SYS_KB):
        _cb_kb("cb_sys", _i, _trg, _rep)

    # -- END CODING BRAIN --
