# PrintSevers

面向 Windows 的本地网页打印服务，默认只允许 localhost 和局域网地址访问，目标打印机为 `Lenovo LJ2205`。用户通过网页上传或拖拽添加文件，服务端逐个校验后加入 SQLite 打印队列；后台调度器默认按 FIFO 选择任务，worker 每次打印前检查打印机状态，失败后暂停整个服务，只能在服务端本机恢复。

## 架构设计

```text
浏览器
  -> FastAPI Web/API
      -> IP 访问控制中间件
      -> HTTP Basic 管理员认证
      -> 上传校验与安全文件名
      -> SQLite 队列/服务状态
      -> FIFO 打印调度器
      -> 后台 PrintWorker
          -> Windows 打印机状态检查
          -> SumatraPDF / LibreOffice / Windows Shell 打印命令
          -> 失败后暂停服务
```

关键文件：

- `app/main.py`：应用工厂、生命周期、日志和后台 worker。
- `app/run_server.py`：读取配置后启动 Uvicorn 服务，并监控启动脚本父进程。
- `app/security.py`：局域网默认放行、公网白名单、管理员认证、本机恢复限制。
- `app/upload_validation.py`：扩展名、文件头、大小和安全文件名校验。
- `app/queue_store.py`：SQLite 打印队列、调度字段和暂停状态持久化。
- `app/scheduler.py`：打印调度器，默认 FIFO，预留优先级和定时打印扩展。
- `app/printer.py`：Lenovo LJ2205 的 Windows 状态检查与打印命令封装。
- `app/worker.py`：执行调度器选中的任务，打印前检查状态，失败即暂停。
- `scripts/local_admin.py`：服务端本机命令行暂停/恢复/查看状态。
- `scripts/deploy.ps1`：一键部署脚本，安装依赖并扫描 SumatraPDF/LibreOffice 路径。
- `scripts/start_foreground.ps1`：前台守护启动脚本，实时输出并写入启动日志。
- `deploy.bat`：Windows 双击一键部署脚本。
- `start_server.bat`：Windows 双击一键启动脚本，读取根目录 `config.ini` 启动服务。
- `package_release.bat`：Windows 双击一键打包脚本，生成可分发 zip。

## 安装

推荐直接双击根目录的 `deploy.bat`。它会自动完成：

- 检查必要文件。
- 创建 `.venv` 虚拟环境。
- 安装 `requirements.txt` 中的依赖。
- 扫描 SumatraPDF 和 LibreOffice 的常见安装位置、PATH 和注册表 App Paths。
- 将扫描到的路径写入 `config.ini` 的 `[printer]` 配置。
- 记录部署日志到 `data/logs/deploy-latest.log`。

命令行部署：

```powershell
.\deploy.bat
```

也可以手动安装：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

编辑 `config.ini`，至少修改管理员密码：

```ini
[auth]
admin_username = admin
admin_password = 请换成强密码

[printer]
printer_name = Lenovo LJ2205
```

## 连接 Lenovo LJ2205

1. 在 Windows 安装 Lenovo LJ2205 官方驱动，并确认系统中能正常打印测试页。
2. 用 PowerShell 确认打印机名称：

```powershell
Get-Printer | Select-Object Name, PrinterStatus, WorkOffline
```

3. 如果名称不是 `Lenovo LJ2205`，把 `config.ini` 里的 `printer_name` 改成实际名称。
4. 推荐安装 SumatraPDF 并配置 `sumatra_pdf_path`，PDF 打印会更可靠。运行 `deploy.bat` 会自动扫描并记录路径；留空时服务运行时也会自动查找常见安装路径。
5. 如需打印 Word/RTF/TXT，推荐安装 LibreOffice 并配置 `libreoffice_path`。运行 `deploy.bat` 会自动扫描并记录路径；留空时服务运行时也会自动查找常见安装路径。
6. 图片会优先调用 Windows 画图打印；其它格式才回退到 Windows Shell 的 `PrintTo/Print`。

PDF 打印如果报“没有关联可打印程序”，请在 `config.ini` 中设置：

```ini
[printer]
sumatra_pdf_path = C:\Program Files\SumatraPDF\SumatraPDF.exe
```

Office/文本文件打印如果报“没有关联可打印程序”，请设置：

```ini
[printer]
libreoffice_path = C:\Program Files\LibreOffice\program\soffice.exe
```

## 启动

Windows 可直接双击根目录的 `start_server.bat`。脚本会自动创建 `.venv`、安装依赖，然后读取 `config.ini` 里的 `host` 和 `port` 启动服务。

启动窗口会保持活跃并实时输出日志。日志同时写入：

```text
data/logs/start-server-时间戳.log
data/logs/start-server-latest.log
```

按 `Ctrl+C` 或关闭这个启动窗口会停止服务；启动入口还会监控父进程，避免窗口关闭后服务残留在后台。

也可以手动启动：

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

本机访问：

```text
http://127.0.0.1:8000
```

局域网访问时，用服务端电脑的内网 IP：

```powershell
ipconfig
```

例如：

```text
http://192.168.1.20:8000
```

## 文件上传与队列

默认支持：

```text
.pdf, .png, .jpg, .jpeg, .bmp, .gif, .tif, .tiff, .doc, .docx, .rtf, .txt
```

网页上传区域支持点击选择和拖拽添加文件，可以一次添加多个文件。提交时页面会锁定上传按钮，避免重复提交；服务端会逐个处理文件，并在页面展示每个文件的入队结果或失败原因。旧的单文件接口 `/api/upload` 保持兼容，新的批量接口为 `/api/uploads`。

上传时会做这些检查：

- 文件大小不得超过 `config.ini` 中的 `max_upload_mb`。
- 扩展名必须在允许列表中。
- PDF、图片、Office 文档、RTF 会校验基础文件头。
- 文件名会去掉路径、Windows 非法字符和控制字符。

队列状态包括：

- `waiting`：等待中。
- `printing`：打印中。
- `completed`：已提交并完成本次 worker 流程。
- `failed`：失败，服务会自动暂停。
- `deleted`：管理员删除。

调度器默认使用 FIFO：按任务创建时间从早到晚选择下一个 `waiting` 任务。队列表已预留 `priority` 和 `scheduled_at` 字段，后续可扩展优先级调度和定时打印；调度前如果服务已暂停，worker 不会继续处理任务。

## 打印机状态与失败暂停

每个任务打印前，`app/printer.py` 会通过 PowerShell 调用 `Get-Printer` 和 `Win32_Printer` 检查：

- 打印机是否存在。
- 是否脱机。
- 是否处于错误、缺纸、卡纸、暂停、未知等状态。

如果打印前检查失败、打印命令失败或提交后状态异常：

1. 当前任务标记为 `failed`。
2. 服务状态标记为暂停。
3. 后续任务不再继续处理。
4. 日志写入 `data/logs/print-server.log`。

## 恢复服务

网页恢复只能在服务端本机访问时执行：

```text
http://127.0.0.1:8000
```

点击“本机恢复”会触发管理员 Basic Auth。局域网或公网来源会被拒绝。

也可以在服务端本机执行：

```powershell
python scripts/local_admin.py status
python scripts/local_admin.py resume
python scripts/local_admin.py pause --reason "维护打印机"
```

恢复服务不会自动重试失败任务。管理员可以先确认失败原因，再在网页中对失败任务点“重试”。

## 公网通道

默认公网关闭：

```ini
[access]
public_access_enabled = false
```

未来如果需要开放公网，建议放在反向代理或 VPN 后面，再启用白名单：

```ini
[access]
public_access_enabled = true
public_ip_whitelist = 203.0.113.10,198.51.100.0/24
```

如果使用反向代理，并且需要读取真实客户端 IP：

```ini
[access]
trust_proxy_headers = true
trusted_proxy_ips = 127.0.0.1,192.168.1.2
```

只有可信代理的 `X-Forwarded-For` 会被采信。公网白名单之外的 IP 会返回 `403`。

## 管理员认证

管理员操作包括：

- 暂停服务。
- 本机恢复。
- 删除任务。
- 重试失败任务。

这些操作都使用 HTTP Basic：

```ini
[auth]
admin_username = admin
admin_password = 请换成强密码
```

如需让上传也要求认证：

```ini
[auth]
require_auth_for_upload = true
```

## 测试

```powershell
pip install -e ".[test]"
pytest
```

不连接真实打印机时，可用 dry-run 模式验证队列流程：

```ini
[printer]
dry_run = true
```

## 打包

双击根目录的 `package_release.bat`，会在 `dist/` 下生成完整 Windows 分发包：

```text
dist/PrintSevers-版本号-windows-时间戳.zip
```

压缩包会包含源码、部署脚本、启动脚本、`config.ini`、测试和说明文档；不会包含 `.git`、`data/`、虚拟环境、缓存、日志或队列数据库。

命令行打包：

```powershell
.\package_release.bat -NoPause
```

## 注意事项

- Windows Shell 打印只能确认任务已交给关联应用，不能保证打印机物理出纸成功。
- PDF 推荐使用 SumatraPDF，Word/RTF/TXT 推荐使用 LibreOffice。
- 公网开放前务必修改管理员密码，并在防火墙/反向代理层再次限制来源。
