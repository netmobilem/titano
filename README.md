# TiTaN Management Panel

پنل مستقل مدیریت کاربران، کانفیگ‌ها، نودها و Subscription با UI فارسی RTL. این پروژه از کد، Template یا ساختار داخلی NewYork کپی نشده است.

## اجرای محلی
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data python app.py
```
سپس `http://localhost:8080` را باز کنید.

ورود اولیه:
```text
admin / admin123
```
در استفاده واقعی حتماً `ADMIN_PASSWORD` و `SECRET_KEY` را تنظیم کنید.

## Deploy روی Railway
1. این پروژه را در یک GitHub repository قرار دهید.
2. در Railway گزینهٔ **Deploy from GitHub Repo** را انتخاب کنید.
3. Railway به‌صورت خودکار Dockerfile را build می‌کند.
4. در Service → Volumes یک Volume بسازید و Mount Path را دقیقاً بگذارید:
   `/app/data`
5. هیچ Variable اجباری برای اجرای اولیه لازم نیست. Dockerfile به‌صورت پیش‌فرض از این مقادیر استفاده می‌کند:
```text
DATA_DIR=/app/data
PORT=8080
APP_PORT=5000
XRAY_PORT=10000
```
در صورت نیاز به امنیت بیشتر، می‌توانی بعداً `ADMIN_PASSWORD` و `SECRET_KEY` را اضافه کنی، اما Deploy بدون آن‌ها نیز انجام می‌شود.
6. از Settings → Networking یک Public Domain بسازید.

برنامه فقط یک Service است و داخل آن این فرآیندها مدیریت می‌شوند:
```text
Nginx : Railway PORT
Flask/Gunicorn : 127.0.0.1:5000
Xray : 127.0.0.1:10000
```
Nginx مسیر `/xray/` را به Xray و سایر مسیرها را به پنل می‌فرستد. مقدار `PORT` توسط Railway تعیین می‌شود و داخل برنامه Hard-code نشده است.

Healthcheck:
```text
/health
```

## Persistence
تمام موارد مهم زیر `DATA_DIR` ذخیره می‌شوند:
```text
/app/data/titan.sqlite3
/app/data/xray/config.json
/app/data/xray/xray.log
/app/data/nginx/default.conf
```
بدون Volume، Railway ممکن است با تعویض Container اطلاعات را حذف کند.

## Xray
Image در زمان Build، Xray Core رسمی را دانلود می‌کند و در Runtime فایل Config تولیدشده را اجرا می‌کند. Config هنگام Boot و بعد از تغییرات مدیریتی بازتولید می‌شود.

پروتکل‌های متداول VLESS، VMess، Trojan و Shadowsocks به ساختار Xray متصل هستند. گزینه‌های Hysteria2 و WireGuard در مدل و UI نگهداری می‌شوند، اما اجرای native آن‌ها به Core جداگانه و در مورد Hysteria2 به UDP نیاز دارد؛ Railway public HTTP service برای UDP عمومی مناسب نیست. بنابراین این دو گزینه نباید به‌عنوان اجرای تضمینی Xray روی Railway تبلیغ شوند.

## تست Persistence
1. در پنل یک User، Node و Subscription بسازید.
2. سرویس را Restart کنید.
3. دوباره Login کنید؛ اطلاعات باید باقی بمانند.
4. این تست فقط زمانی معیار واقعی است که Volume به `/app/data` وصل باشد.

## ساخت ZIP برای GitHub
فایل ZIP انتشار را می‌توان با این دستور ساخت:
```bash
zip -r titan-panel-release.zip . -x 'data/*' '.venv/*' '__pycache__/*' '*.sqlite3' 'uploads/*'
```
