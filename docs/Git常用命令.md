# Git 常用命令速查

> **用法**:按场景找,复制粘贴、改改路径即可。`⚠` = 危险(会丢改动或改写历史)。
> 讲道理的版本见 [Git与GitHub使用入门.md](Git与GitHub使用入门.md);本文只列命令。
> 本机 git 2.55,新命令(`git switch` / `git restore`)已支持;老教程里的
> `git checkout` 写法在括号里给出。

## 0. 先记这 8 条(日常 90% 的情况)

```bash
git status                     # 现在有什么改动没提交(最常用,拿不准就敲它)
git diff                       # 具体改了什么内容
git add -A                     # 把所有改动放进暂存区
git commit -m "feat: 说明"     # 打一个快照
git push                       # 送到 GitHub
git pull                       # 把远程的改动拉下来
git log --oneline -10          # 最近 10 个提交
git restore <文件>             # ⚠ 丢弃某个文件未提交的改动
```

## 1. 看状态与差异

```bash
git status                     # 哪些改了、哪些已暂存、哪些未跟踪
git status -s                  # 精简版(?? = 未跟踪,M = 改过,A = 已暂存)
git diff                       # 工作区 vs 暂存区(还没 add 的改动)
git diff --staged              # 暂存区 vs 上次提交(即将提交的内容)★ 提交前扫一眼
git diff HEAD                  # 工作区 vs 上次提交(所有未提交改动)
git diff HEAD~1                # 工作区 vs 上上次提交
git diff <文件>                # 只看某个文件
git diff main origin/main      # 本地 main 与远程 main 的差异
```

## 2. 提交与推送

```bash
git add <文件>                 # 提交单个文件(推荐,历史更清楚)
git add <目录>/                # 提交整个目录
git add -A                     # 提交所有改动(含新增、删除)
git add -p                     # 逐块挑选要提交的内容(同一个文件只提交一部分)

git commit -m "说明"           # 提交
git commit -am "说明"          # 已跟踪文件的改动直接提交(不能加新文件)
git commit --amend             # ⚠ 改写最后一次提交(改消息/补漏掉的文件;未 push 时用)

git push                       # 推送(首次要 git push -u origin main)
git push -u origin main        # 首次推送:顺便记住对应关系,以后直接 git push
git push origin <分支名>       # 推某条分支
git push --tags                # 推标签
```

**提交信息前缀**(本项目惯例,Conventional Commits):

```bash
git commit -m "feat: 增加边缘规整度口径"      # 新功能
git commit -m "fix: 空输入时温度矩阵崩溃"     # 修 bug
git commit -m "docs: 补充参数表"              # 只改文档
git commit -m "test: 补 window_guard 用例"    # 只改测试
git commit -m "refactor: 合并重复的掩膜逻辑"  # 重构,行为不变
git commit -m "chore: 更新依赖"               # 杂项
```

## 3. 拉取与同步

```bash
git pull                       # = fetch + merge:把远程改动拉下来并合并
git pull --rebase              # 拉下来并把你的提交垫在别人之上(历史更直,无合并提交)
git fetch                      # 只下载不合并(想先看看再决定时用)
git fetch --prune              # 顺便清掉远程已删除的分支引用
```

**推送被拒(`rejected / fetch first`)** = 远程有别人的新提交:

```bash
git pull --rebase              # 先把远程的拉下来垫在前面
git push                       # 再推
```

## 4. 分支

```bash
git branch                     # 本地有哪些分支(* = 当前)
git branch -a                  # 含远程分支
git switch -c feat/xxx         # 新建并切到新分支    (老写法:git checkout -b)
git switch main                # 切回主干            (老写法:git checkout main)
git switch -                   # 切回上一个分支(来回横跳很方便)

git merge feat/xxx             # 把某分支合并进当前分支
git merge --abort              # 放弃正在进行的合并,回到合并前

git branch -d feat/xxx         # 删除已合并的本地分支
git branch -D feat/xxx         # ⚠ 强制删除(未合并也删)
git push origin --delete feat/xxx   # 删除远程分支

git branch -m 新名字           # 重命名当前分支(git branch -M 强制)
```

**分支 + PR 的完整流程**(推荐,不直接推 main):

```bash
git switch main && git pull            # ① 基于最新 main
git switch -c feat/新功能              # ② 开分支
# ... 改代码 ...
git add -A && git commit -m "feat: ..."  # ③ 提交
git push -u origin feat/新功能           # ④ 推分支
# ⑤ 网页点 "Compare & pull request" 开 PR,评审后 Merge
git switch main && git pull             # ⑥ 合并后回主干更新
git branch -d feat/新功能                # ⑦ 清理
```

## 5. 撤销与回退 ⚠

**按"退到哪一步"选命令**:

| 情况 | 命令 | 后果 |
|---|---|---|
| 改了文件,还没 `add` | `git restore <文件>` | ⚠ 丢弃这些改动,不可恢复 |
| 同上,但想全部丢弃 | `git restore .` | ⚠ 丢掉所有未暂存的改动 |
| 已 `add`,想拿出来 | `git restore --staged <文件>` | 只出暂存区,**改动还在** |
| 刚 `commit`,想改消息 | `git commit --amend` | ⚠ 改写提交(未 push 时用) |
| 刚 `commit`,想撤销但保留改动 | `git reset --soft HEAD~1` | 提交没了,改动回到暂存区 |
| 已 `push`,想撤销 | `git revert <哈希>` | **安全**:新建反向提交,历史保留 |
| 想看某个历史版本 | `git switch --detach <哈希>` | 看完 `git switch main` 回来 |
| 合并到一半想放弃 | `git merge --abort` | 回到合并前 |

```bash
git restore <文件>             # ⚠ 丢弃单个文件未提交的改动 (老写法:git checkout -- <文件>)
git restore --staged <文件>    # 从暂存区拿出来,改动保留 (老写法:git reset HEAD <文件>)
git revert <哈希>              # 安全撤销已推送的提交
git reset --hard HEAD          # ⚠⚠ 丢掉所有未提交改动,不可恢复
```

**两条铁律**:

1. **已 push 的提交不要 `--amend` / `--force`**——别人可能已经拉了,重写历史会让他们一团乱。用 `git revert`。
2. `git restore` / `reset --hard` 丢掉的改动**找不回来**,敲之前先 `git diff`。

真推错了需要强推(仅限**自己独占**的分支):

```bash
git push --force-with-lease    # 比 --force 安全:远程被别人改过时会拒绝
```

## 6. 看历史

```bash
git log --oneline              # 一行一个提交
git log --oneline -10          # 最近 10 条
git log --oneline --graph      # 带分支线,看得出合并
git log --stat                 # 每个提交改了哪些文件、多少行
git log --author="名字"        # 只看某人的提交
git log --since="1 week ago"   # 最近一周
git log -p <文件>              # 某个文件的完整改动历史
git log --oneline -- <路径>    # 只看影响该路径的提交

git show <哈希>                # 看某个提交具体改了什么
git show <哈希>:<文件路径>     # 看某次提交时该文件的内容
git blame <文件>               # 逐行显示"这行是谁、哪次提交改的"
```

## 7. 远程仓库

```bash
git remote -v                  # 当前连的远程地址
git remote add origin <URL>    # 添加远程(重新 init 后要重加)
git remote set-url origin <URL>  # 改远程地址(换仓库名/换 HTTPS↔SSH)
git remote remove origin       # 删掉远程配置

git ls-remote origin           # 远程仓库通不通、有哪些分支(排查第一步)★
git ls-remote --heads origin   # 只看分支
```

## 8. 排查问题

```bash
git status                     # 先敲它:大多数问题看一眼状态就清楚了
git ls-remote origin           # 远程通不通、仓库存不存在
git config --list              # 当前所有配置
git config --get user.name     # 提交用的名字
git config --get remote.origin.url   # 远程地址
git config --global user.name "名字" # 设置(全局,一次即可)
git config --global user.email "邮箱"

git check-ignore -v <文件>     # 这个文件为什么没被提交?(显示是 .gitignore 哪一行挡的)★
git ls-files                   # 仓库里已跟踪的全部文件
```

| 报错 | 原因 | 怎么办 |
|---|---|---|
| `Repository not found` | 仓库没建,或是私有仓库而你没登录 | 网页确认地址;或重新登录(见下) |
| `Authentication failed` | 凭据过期 | 控制面板 → 凭据管理器 → Windows 凭据 → 删 `git:https://github.com` → 下次 push 重新弹窗 |
| `Updates were rejected` | 远程有你没有的提交 | `git pull --rebase` 再 `git push` |
| `nothing to commit` | 没有新改动(或全被 .gitignore 挡了) | `git status -s` / `git check-ignore -v <文件>` |
| 大文件推不上去 | 单文件 > 100 MB | 加进 `.gitignore`,已跟踪的用 `git rm --cached` 摘掉 |
| 中文文件名显示成 `\344\277\256` | 默认转义 | `git config --global core.quotepath false` |

## 9. 本项目常用命令(非 git,但天天用)

```bash
# 跑检测(结果落在 data/output/formal/<图名>/ 与 data/output/images/<图名>/)
python scripts/run_inspection.py --input data/raw/test04.JPG
python scripts/run_inspection.py --input data/raw            # 整个目录一起跑

# 跑测试(当前:149 通过、3 失败,那 3 条是既有问题,见 logs/修改日志.md J 节)
python -m pytest
python -m pytest tests/test_seepage_guard.py      # 只跑一个文件
python -m pytest -k "window_guard"                # 只跑名字含 window_guard 的用例
python -m pytest -x                               # 第一个失败就停

# 重新生成演示数据
python scripts/make_demo_data.py

# 提交前的一整套
git status && python -m pytest && git add -A && git commit -m "feat: 说明" && git push
```

## 10. 配置一次,长期受益

```bash
git config --global user.name "La0Shen"
git config --global user.email "你的邮箱"
git config --global core.quotepath false      # 中文文件名正常显示
git config --global core.autocrlf true        # Windows 行尾处理
git config --global init.defaultBranch main   # 新仓库默认分支叫 main
git config --global alias.st "status -s"      # 之后可以用 git st
git config --global alias.lg "log --oneline --graph --decorate -15"   # git lg 看历史
```

> 去掉 `--global` 就是只对当前仓库生效(写在 `.git/config` 里,不会提交)。
