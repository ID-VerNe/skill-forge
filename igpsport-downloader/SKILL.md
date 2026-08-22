---
name: igpsport-downloader
version: 1.0.0
description: 按 iGPSPORT 路书编号(roadbook id)或关键词下载路书,自动登录 iGPSPORT 取 token、搜索路书、拉取航点、生成可直接导入地图的 GPX 文件。用户说"下载路书"、"igpsport 路书"、"路书编号"、"路书转 gpx"、"igpsport 下 route"、"把这个路书导出来" 时触发。不要把具体路书名(如"环车八岭")写进触发词——那是路书内容,不是技能触发条件。注意区分中国站(prod.zh.igpsport.com)与国际站(prod.en.igpsport.com),两站账号和路书编号均不互通。
---

# iGPSPORT 路书下载器

输入 iGPSPORT 路书编号(或关键词),自动登录 → 搜索 → 拉取航点 → 生成 GPX 文件,可直接导入 OsmAnd / Garmin / 两步路 / Strava 等地图软件。

## 核心事实(必须告知用户)

- **中国站与国际站是两套独立系统**:账号不通用、路书编号不互通、数据也不一样。同一个编号在两个站可能指向完全不同的路书。
- 小红书等平台分享的国内路书,通常是**中国站**的编号,必须用中国站账号登录才能拉到。
- 登录接口报 `code:1002 "Password error"` 时,可能是密码错,也可能是该账号根本没在对应站注册(接口不区分)。
- iGPSPORT 没有公开 API,以下接口是逆向自网页版的私有接口,可能失效,失效时需要重新用 bb-browser 抓包确认。
- **token 持久化**:默认登录后 token 缓存在 `~/.cache/igpsport/`(按 api+邮箱分文件,权限 600),有效期内复用,不重复登录。要强制重新登录用 `--clear-token`。

## 环境要求

- Python 3 + `requests` 库(`pip install requests`)
- 一个 iGPSPORT 账号及密码(中国站账号和国际站账号要分开记)

## 使用方法

脚本位置:`scripts/igpsport_download.py`(本 skill 目录下)。

### 1. 按路书编号下载(推荐,精确)

```bash
python scripts/igpsport_download.py \
  --route 123456 \
  --email "你的邮箱" \
  --password "你的密码" \
  --api "https://prod.zh.igpsport.com" \
  --outdir ./downloads
```

### 2. 按关键词搜索后再下载

```bash
python scripts/igpsport_download.py \
  --search "某路线名" \
  --email "你的邮箱" \
  --password "你的密码" \
  --api "https://prod.zh.igpsport.com"
```

搜索模式会列出所有匹配路书(id / 标题 / 距离 / 区域 / 作者),选取目标 id 后用 `--route` 精确定位下载。

### 3. 国际站(若目标路书在国际站)

```bash
python scripts/igpsport_download.py \
  --route 123456 \
  --email "国际站邮箱" \
  --password "国际站密码" \
  --api "https://prod.en.igpsport.com"
```

### 参数说明

| 参数 | 必填 | 说明 |
|------|------|------|
| `--route` | 与 `--search` 二选一 | 路书编号(数字) |
| `--search` | 与 `--route` 二选一 | 关键词搜索 |
| `--email` | 是 | iGPSPORT 账号邮箱/手机号 |
| `--password` | 是 | 账号密码 |
| `--api` | 否 | 默认国际站 `https://prod.en.igpsport.com`;中国站填 `https://prod.zh.igpsport.com` |
| `--outdir` | 否 | 输出目录,默认当前工作目录(Claude Code 的启动位置,即 `os.getcwd()`)。生成的文件在 `{outdir}/{routeId}-{标题}.gpx` |
| `--clear-token` | 否 | 清除该 api+邮箱的缓存 token 后退出(换账号/强制重新登录时用) |

## 支持的操作 & 判定

- 登录成功判断:`code == 0` 且返回 `access_token`
- 搜索接口:`GET /service/web/api/Routes/RouteListForWeb?type=find&key={关键词或编号}`
- 详情接口:`GET /service/web/api/Routes/DetailsRoutesWeb?routeId={编号}`(返回 `routeInfo.tracks` 航点数组,含 latitude / longitute / alt)
- 生成 GPX 1.1:每个航点为 `<trkpt><ele>…</ele></trkpt>`,起点终点为 `<wpt>`
- 输出文件名:`{routeId}-{标题}.gpx`
- 验证产物:`grep -c "<trkpt" *.gpx` 与路书航点数一致;`python -c "import xml.dom.minidom as m; m.parse('文件')"` 校验 XML

## 常见失败 & 处理

| 现象 | 原因 | 处理 |
|------|------|------|
| `code:1002 Password error` | 密码错 / 账号不在该站注册 | 让用户确认站别和密码;或让用户把密码重置成已知值(重置是即时生效的) |
| HTTP 403 | 被风控或站别错误 | 加浏览器 UA + Referer `https://app.igpsport.cn/`;确认用的是对应站的 API |
| 搜索 0 条 | 编号属于另一站 / 路书已删 | 换另一个站试;或改用关键词 `--search` |
| 接口 404 | 私有接口已变更 | 用 bb-browser 打开 `https://app.igpsport.cn/login`,登录后进"Routes"→搜索,抓包看最新接口路径 |

## 备选:用 bb-browser 交互式抓取(接口失效时)

1. `bb-browser open https://app.igpsport.cn/login`(中国站)或 `https://app.igpsport.com/login`(国际站)
2. 让用户在 bb-browser 的可见窗口里**手动登录**(避免处理 React 表单状态)
3. `bb-browser eval "localStorage.getItem('IGSTOKEN')"` 拿到 token
4. 用该 token 直接调详情接口或让脚本复用 token

注意:bb-browser 启动的是独立 Chrome 实例,不会自动带上用户个人 Chrome 的登录态;登录必须在 bb-browser 自己的窗口内完成。