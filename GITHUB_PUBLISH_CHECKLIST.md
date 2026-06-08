# GitHub Publish Checklist

这个项目已经整理成适合开源发布的仓库结构。发布前建议按下面步骤检查。

## 1. 配置 git 身份

如果本机还没有配置 git 用户名和邮箱：

```bash
git config --global user.name "你的名字或 GitHub 用户名"
git config --global user.email "你的邮箱或 GitHub noreply 邮箱"
```

只想对当前仓库生效，可以去掉 `--global`。

## 2. 本地提交

```bash
git status
git commit -m "Initial open-source release"
```

## 3. 创建 GitHub 仓库

方式一：在 GitHub 网页新建一个 public repository，例如：

```text
quant_driver_factor
```

然后回到本地执行：

```bash
git remote add origin https://github.com/<your-username>/quant_driver_factor.git
git push -u origin main
```

方式二：安装并登录 GitHub CLI：

```bash
brew install gh
gh auth login
gh repo create quant_driver_factor --public --source=. --remote=origin --push
```

## 4. 发布后检查

- README 能否正常展示。
- GitHub Actions 是否通过。
- `LICENSE` 是否显示为 MIT。
- `data/raw/`、`outputs/` 等生成文件是否没有被提交。
- 如果后续接入真实数据，不要提交付费数据、Token 或账户信息。
