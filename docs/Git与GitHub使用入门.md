# Git 与 GitHub 入门:把仓库管起来、推上去、和别人一起改

> 目标读者:第一次用 Git / GitHub 的同学,以及要把本仓库分享给合作者的人。
> 本文**不是**命令大全,而是"这个项目该怎么用"——每条命令都配上"什么时候用、
> 用了之后会发生什么"。所有命令都在项目根目录(`wall-defect-single/`)下执行。

## 0. 先认清三件事

### ① Git 和 GitHub 不是一回事

| | 是什么 | 在哪 |
|---|---|---|
| **Git** | 版本管理工具:记录每次改动、能回退、能分支 | 你电脑上(已装,`git --version` 有输出就行) |
| **GitHub** | 存放 Git 仓库的网站:备份 + 协作 + 展示 | 网页上(github.com) |

没有 GitHub,你也能用 Git 管版本;有了 GitHub,别人才拿得到你的代码、才能一起改。

### ② 本仓库现在是什么状态

在项目根目录跑这三条,就能看清自己站在哪儿(建议养成习惯):

```bash
git status          # 有哪些改动没提交?
git log --oneline   # 提交历史
git remote -v       # 这个仓库连着哪个远程地址
```

本仓库**当前的真实状态**(2026-09-19):

```
分支:main,已有 1 个提交(60dc209 chore: update docs and source files)
远程:origin → https://github.com/La0Shen/Infrared-Wall-Defect-Detection.git
```

⚠ **远程地址配好了,但 GitHub 上那个仓库还不存在**——直接推会报
`remote: Repository not found`。所以第 2 节要做的第一件事是**先去网页建仓库**。

### ③ 三条命令走完 90% 的日常

```bash
git add -A              # ① 把改动放进"待提交"篮子
git commit -m "说明"    # ② 打一个快照(本地)
git push                # ③ 快照送到 GitHub
```

下面所有内容,都是围绕这三条展开的细节。

---

## 1. 一张图看懂 Git 在做什么

```
  你改的文件                暂存区                 本地仓库               GitHub
 (工作区 working)        (staging/index)          (repository)          (remote)
       │                       │                       │                     │
       │   git add -A          │                       │                     │
       ├──────────────────────►│                       │                     │
       │                       │  git commit -m "…"    │                     │
       │                       ├──────────────────────►│                     │
       │                       │                       │     git push        │
       │                       │                       ├────────────────────►│
       │                       │                       │                     │
       │◄──────────────────────┴───────────────────────┴─────────────────────┤
       │                      git pull(把别人的改动拉下来)
```

**为什么要"暂存区"这么麻烦的一段?** 因为它让你**挑着提交**:今天同时改了算法
和文档,你可以只把算法提交成一个 commit、文档提交成另一个。这样历史才读得懂
(`git add 某个文件` 而不是 `git add -A`)。

⚠ 三个词先记住,后面一直用:**工作区**(你能编辑的文件)、**提交**(commit,
一次快照,有哈希号如 `60dc209`)、**远程**(origin,指 GitHub 上那份)。

---

## 2. 把本仓库推上 GitHub(首次)

### 2.1 在网页创建"空仓库"

1. 打开 <https://github.com/new>
2. **Repository name** 填 `Infrared-Wall-Defect-Detection`
   (GitHub 仓库名不能有空格,习惯用连字符;大小写不敏感)
3. **Description** 可填:`无人机热红外外墙空鼓/渗水检测(规则算法,单帧基线)`
4. 选 **Public**(公开)或 **Private**(私有)——见 §4.1 的说明
5. **下面三个初始化选项一个都不要勾**(README / .gitignore / license):
   你本地已经有完整内容了,勾了会造出一个"远程也有提交"的分叉,首次推送会
   被拒(`Updates were rejected`),还得额外折腾合并。
6. 点 **Create repository**

创建完网页会显示一堆命令,**不用照抄**——因为本地已经把远程配好了,直接看下一步。

### 2.2 首次推送

```bash
git push -u origin main
```

- `origin` = 远程仓库的名字(标准叫法,`git remote -v` 能看到它就是那个 GitHub 地址)
- `main` = 本地分支名
- `-u` = `--set-upstream`:**记住这条对应关系**。以后只敲 `git push`
  就知道往哪推,不用再写全。只有第一次需要 `-u`。

**会弹登录窗口**(本机凭据助手是 `manager` = Git Credential Manager):

- 弹浏览器 → 用你的 GitHub 账号登录 → 授权 → 回到终端即完成
- 之后凭据被记住,以后 push 不再问
- 如果没弹窗、直接在终端报 `Authentication failed`:见 §2.4

### 2.3 验证

```bash
git status          # 应显示 "Your branch is up to date with 'origin/main'"
```

再刷新网页,应该能看到 README.md、src/、docs/ 等文件都在了。

### 2.4 常见报错怎么办

| 报错 | 原因 | 怎么办 |
|---|---|---|
| `remote: Repository not found` | 仓库还没在 GitHub 上创建;**或者**是私有仓库而你没登录/没权限 | 先确认 §2.1 做过了;再去 §2.2 走一次登录。排查时打开 `https://github.com/La0Shen/Infrared-Wall-Defect-Detection` 看是不是 404 |
| `Authentication failed` | 凭据过期/没登录 | 删掉旧凭据重来:控制面板 → 凭据管理器 → Windows 凭据 → 删掉 `git:https://github.com`;再 `git push` 会重新弹窗 |
| `Updates were rejected … fetch first` | 远程有你本地没有的提交(通常是建仓库时勾了 README) | `git pull --rebase origin main` 把远程的拉下来垫在本地提交之前,再 `git push` |
| `Permission denied (publickey)` | 用了 SSH 地址但没配 SSH key | 要么改用 HTTPS 地址(`git remote set-url origin https://github.com/...`),要么配 SSH key |
| 卡住不动 | 网络问题(国内访问 GitHub 常见) | 等一会儿;或配置代理后重试 |

### 2.5 备选:装 gh 命令行(可选,但很省事)

GitHub 官方 CLI,能一条命令建仓库并推送,以后开 PR 也不用开网页:

```bash
winget install GitHub.cli     # Windows 装法
gh auth login                 # 按提示登录
gh repo create Infrared-Wall-Defect-Detection --public --source=. --push
```

---

## 3. 日常本地管理(一个人写代码时)

### 3.1 开工前先看一眼状态

```bash
git status          # 我改了什么?有没有没提交的?
git pull            # 如果和别人协作,先把远程的改动拉下来(一个人写可跳过)
```

### 3.2 改完一批东西 → 提交 → 推送

```bash
git status                    # 确认改了哪些文件
git diff                      # 看看具体改了什么(很重要,提交前扫一眼)
git add src/thermal_inspect/window_guard.py    # 挑要提交的文件
git add -A                                     # 或:全部一起提交
git commit -m "fix: 窗口保护把真渗漏误判为窗户"
git push
```

### 3.3 提交信息怎么写

本仓库现有提交是 `chore: update docs and source files`,用的是
[Conventional Commits](https://www.conventionalcommits.org/) 风格——建议沿用:

| 前缀 | 用在 |
|---|---|
| `feat:` | 新功能(如 `feat: 增加边缘规整度口径`) |
| `fix:` | 修 bug(如 `fix: 温度矩阵在空输入时崩溃`) |
| `docs:` | 只改文档 |
| `test:` | 只改测试 |
| `refactor:` | 重构,行为不变 |
| `chore:` | 杂项(依赖、配置) |

一句话说清"为什么改",比"改了什么"更有用(改了什么 `git diff` 能看到,
为什么改只有你知道)。

### 3.4 看历史

```bash
git log --oneline              # 一行一个提交
git log --oneline --graph      # 带分支线,看得出合并
git show 60dc209               # 看某个提交具体改了啥
git diff HEAD~1                # 与上一个提交比
```

### 3.5 改错了怎么退(**按"退到哪一步"选命令**)

| 情况 | 命令 | 后果 |
|---|---|---|
| 改了文件,还没 `add` | `git restore <文件>` | 丢弃这些改动(⚠ 不可恢复) |
| 已 `add`,还没 `commit` | `git restore --staged <文件>` | 只从暂存区拿出来,**改动还在** |
| 刚 `commit`,还没 `push`,想改提交信息或补文件 | `git add <漏掉的文件>` 然后 `git commit --amend` | 把这次提交重写掉(哈希会变) |
| 已 `push`,想撤销 | `git revert <哈希>` | **安全**:新建一个"反向提交",历史不丢 |
| 想临时看看旧版本 | `git switch --detach <哈希>` | 看完 `git switch main` 回来 |

⚠ **两条铁律**:
1. **已 `push` 的提交不要用 `--amend` 或 `--force`**——别人可能已经拉下来了,
   重写历史会让他们一团乱。用 `git revert`。
2. `git restore` / `git checkout -- <文件>` 会**永久丢弃**未提交的改动,
   敲之前先 `git diff` 确认。

> 老教程里写的是 `git checkout` / `git reset`,现在推荐用 `git switch`(切分支)与
> `git restore`(还原文件)——名字更直白。本机 git 2.55,两条新命令都支持。

### 3.6 `.gitignore`:哪些东西永远不要提交

本仓库的 `.gitignore` 已经排除了这些(看文件就知道):

```gitignore
data/raw/*        # 真实无人机照片:体积大,且可能是客户的楼
data/output/*     # 处理结果:每次跑都会变
.venv/            # 虚拟环境:几百 MB,别人自己建
__pycache__/      # Python 缓存
```

**要加新的排除项**,直接编辑 `.gitignore` 加一行(支持通配符):

```gitignore
*.JPG
models/*.pth
```

⚠ 如果某个文件**已经被提交过**,再加 `.gitignore` 是没用的(它已经被跟踪了),
要显式从版本控制里摘掉:

```bash
git rm --cached 大文件.bin      # 只从 git 里去掉,文件本身保留在磁盘上
git commit -m "chore: 停止跟踪 大文件.bin"
```

**每次提交前扫一眼 `git status`**:如果列表里出现 `data/`、`.venv/`、几百 MB 的
文件,先停下来把它加进 `.gitignore`,别推上去——GitHub 对单文件 >100 MB 直接拒收,
而且大文件进了历史就很难彻底清掉。

---

## 4. 多人协作

### 4.1 先选权限模型

| | Public(公开) | Private(私有) |
|---|---|---|
| 谁能看 | 所有人 | 只有你和你邀请的人 |
| 谁能改 | 只有你邀请的人(其他人只能 **fork** 后提 PR) | 受邀的人 |
| 适合 | 开源、作品展示、求职作品集 | 课程作业、客户项目、未发表的研究 |

本仓库涉及具体楼栋的照片与参数,**建议先 Private**;要展示时再改成 Public
(Settings → 最下面 Danger Zone → Change visibility)。

### 4.2 把合作者加进来(Private 必须做这步)

网页仓库页 → **Settings → Collaborators → Add people** → 输入对方的 GitHub 用户名
或邮箱 → 对方收到邮件接受后即可推送。

### 4.3 推荐流程:分支 + Pull Request(PR)

即使只有两个人,也**不要直接往 main 上推**。流程是:

```bash
# ① 从最新的 main 开一条分支(分支名说明你要干什么)
git switch main
git pull
git switch -c feat/边缘口径开关

# ② 在分支上正常改、正常提交
git add -A
git commit -m "feat: 边缘规整度拆成两个子口径"
git push -u origin feat/边缘口径开关      # 第一次推这条分支要 -u

# ③ 到 GitHub 网页,会看到 "Compare & pull request" 按钮 → 点它
#    填标题和说明 → Create pull request

# ④ 合作者在网页上评审:逐行评论、要求修改
#    你继续在**同一条分支**上提交并 push,PR 会自动更新

# ⑤ 评审通过 → 网页点 "Merge pull request"
```

合并后清理:

```bash
git switch main
git pull
git branch -d feat/边缘口径开关           # 删本地分支
git push origin --delete feat/边缘口径开关 # 删远程分支
```

**PR 的好处**:改动在合并前能被逐行审阅;讨论记录留在 PR 里;main 始终是能跑的版本。

### 4.4 外部人参与:fork

公开仓库里,没有写权限的人可以:

1. 点网页右上角 **Fork**(把仓库复制一份到自己账号下)
2. 在自己的 fork 上开分支、改、push
3. 点 **Contribute → Open pull request** 向你的仓库提 PR

你在这边照常评审、合并即可。

### 4.5 同步别人的改动

```bash
git pull            # = git fetch(下载) + git merge(合并进当前分支)
```

**推送前先拉**:`git pull` → 解决冲突(见下)→ `git push`。
如果直接 push 被拒(`rejected`),说明远程有别人的新提交,先 pull 再 push。

### 4.6 冲突是怎么回事、怎么解决

冲突 = 你和别人**改了同一个文件的同一处**。Git 不知道听谁的,就把选择权交给你。
`git pull` 或 `git merge` 时出现:

```
Auto-merging src/thermal_inspect/classify.py
CONFLICT (content): Merge conflict in src/thermal_inspect/classify.py
```

打开那个文件,会看到这样的标记:

```python
<<<<<<< HEAD                       ← 你本地的版本
    if f["dT"] < cp.seepage_dt_c:
=======
    if f["dT"] < cp.seepage_dt_c and f["elong"] > 1.5:
>>>>>>> origin/main                ← 远程(别人)的版本
```

**解决三步**:

1. 手工把这一块改成**最终想要的样子**,把 `<<<<<<<`、`=======`、`>>>>>>>` 三行标记**全删掉**
2. `git add <该文件>`(告诉 Git"这个冲突我解决了")
3. `git commit`(Git 会给出一个默认的合并提交信息,直接保存即可)

半路想放弃、回到冲突前的状态:`git merge --abort`。

⚠ 冲突**不可怕**:它不是在报错,而是 Git 在说"这两处我拿不准,你来定"。
改完记得跑一遍 `python -m pytest`,确认没把别人的逻辑改坏。

---

## 5. 本仓库的具体注意事项

### 5.1 别人 clone 下来之后,少两样东西

```bash
git clone https://github.com/La0Shen/Infrared-Wall-Defect-Detection.git
cd Infrared-Wall-Defect-Detection
pip install -r requirements.txt          # 或 pip install -e ".[dev]"
python -m pytest
```

- **没有 `data/raw/` 里的真实照片**(被 `.gitignore` 排除):所以那几条"真实帧真值"
  用例会自动 **skip**(它们写了 `skipif(not 文件.exists())`)。这是**故意设计**的
  ——没数据的机器上测试照样全绿,不会假装通过。
- **没有 `.venv/`**(虚拟环境本地建):`python -m venv .venv` 然后激活安装依赖。

### 5.2 不要提交的东西(再说一遍,因为最容易犯)

- 真实热红外照片(`data/raw/`)——体积 + 隐私
- 处理结果(`data/output/`)——每次跑都变,提交了也没意义
- 训练权重、大模型文件——超过 100 MB GitHub 直接拒

### 5.3 提交前跑一遍测试

```bash
python -m pytest
```

本仓库目前的状态是 **149 通过、3 失败**,那 3 条是 `tests/test_pipeline.py` 里
`save_results(...)` 少传 `out_final` 的**既有问题**(见 `logs/修改日志.md` J 节),
不是新改动引起的。提交前确认"失败的还是那 3 条",就没把新东西改坏。

### 5.4 改了代码,记得同步文档

本仓库的约定(`CLAUDE.md`):**改动要记进 `logs/修改日志.md`**——改了什么、
为什么改、用哪份数据验证的。这是这个项目最有价值的部分之一:参数怎么调出来的、
哪些结论被推翻过,全在那份日志里。提交时把日志和代码放在**同一个 commit**里。

---

## 6. 速查表

```bash
# —— 看状态 ——
git status                     # 最常用:现在有什么没提交
git diff                       # 具体改了什么
git log --oneline --graph      # 历史(带分支线)
git remote -v                  # 连着哪个远程

# —— 提交与推送 ——
git add <文件>                 # 挑文件进暂存区
git add -A                     # 全部
git commit -m "feat: …"        # 打快照
git push                       # 送到 GitHub(首次要 git push -u origin main)

# —— 同步别人的改动 ——
git pull                       # 拉下来并合并
git fetch                      # 只下载不合并(想先看看再说时用)

# —— 分支 ——
git switch -c feat/xxx         # 新建并切到新分支
git switch main                # 切回主干
git branch                     # 本地有哪些分支
git merge feat/xxx             # 把某分支合并进当前分支

# —— 撤销(按危险程度从上到下)——
git restore --staged <文件>    # 从暂存区拿出来,改动保留
git restore <文件>             # ⚠ 丢弃未提交的改动
git commit --amend             # ⚠ 改写最后一次提交(未 push 时用)
git revert <哈希>              # 安全撤销已 push 的提交
git merge --abort              # 放弃正在进行的合并

# —— 一次性排查 ——
git ls-remote origin           # 远程仓库存不存在、能不能连上
git config --list              # 看当前所有 git 配置
```

## 7. 下一步学什么

本文够你把仓库用起来了。想再深入,按这个顺序:

1. **`.gitignore` 的写法**(通配符、目录、`!` 反选)——立刻用得上
2. **PR 的评审流程**(行内评论、要求修改、Squash merge)——协作必经
3. **`git rebase -i`**(整理提交历史为一条条清晰的提交)——熟练后再碰
4. **GitHub Actions**(每次 push 自动跑 `pytest`)——本仓库已经有完整测试,接上去很自然
5. **Git LFS**(真要把大文件入库时)——本项目目前用不到

学命令最舒服的方式是 **`git help <命令>`** 或 `git <命令> -h`,比搜网页准。
