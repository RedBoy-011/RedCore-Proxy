# RedCore-Proxy — Mihomo Edition

ابزار لینوکسی فارسی برای دریافت Subscriptionهای عمومی، تست واقعی نودها با **Mihomo / Clash Meta** و ساخت حداکثر ۸ SOCKS5 محلی برای پنل ثنایی / 3X-UI.

## چرا Mihomo؟

Mihomo محتوای subscription را مستقیماً به‌صورت YAML، URI و Base64 می‌خواند؛ بنابراین پارس دستی و ناقص VLESS، Reality، XHTTP، Hysteria2 و TUIC حذف شده است. Mihomo از هر provider، نودها را می‌گیرد، سپس اسکریپت از API رسمی آن delay واقعی را می‌سنجد. برای هر نود منتخب نیز یک listener SOCKS مستقل روی localhost ساخته می‌شود.

## روند واقعی تست

1. هر لینک ساب به Mihomo به‌عنوان `proxy-provider` داده می‌شود.
2. Mihomo محتوای URI/Base64/YAML را دریافت و بارگذاری می‌کند.
3. همهٔ نودها با API delay Mihomo روی `https://www.gstatic.com/generate_204` تست می‌شوند.
4. ۸ نود سریع‌تر انتخاب می‌شوند.
5. برای هر نود یک SOCKS در `127.0.0.1:10801` تا `10808` ایجاد می‌شود.
6. هر SOCKS با اتصال واقعی SOCKS5 → TLS → HTTP دوباره بررسی می‌شود.
7. فقط پورت‌های واقعاً سالم وارد `sanaei.json` می‌شوند.

## نصب

پس از آپلود فایل‌های این پوشه در repository عمومی `RedBoy-011/RedCore-Proxy`:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/RedBoy-011/RedCore-Proxy/main/install.sh)
```

## استفاده

```bash
titan
```

یا خط فرمان:

```bash
# این مقادیر را با نام و لینک خودتان جایگزین کنید.
titan subs add 'نام ساب' 'https://example.com/your-subscription'
titan test-subs
titan refresh
titan status
titan socks-test 10801
titan json
```

نصب‌کننده هیچ لینک سابی اضافه نمی‌کند. هر ساب فقط با دستور `titan subs add` یا گزینهٔ «افزودن ساب» ثبت می‌شود.

## فایل‌های سرور

| مسیر | توضیح |
| --- | --- |
| `/etc/titan/subs.txt` | هر خط: `نام | لینک subscription` |
| `/etc/titan/mihomo.yaml` | کانفیگ تولیدشدهٔ Mihomo |
| `/etc/titan/sanaei.json` | فقط SOCKSهای سالم برای پنل ثنایی |
| `/etc/titan/status.json` | گزارش تست و نودهای نهایی |
| `/var/log/titan/refresh.log` | لاگ فرآیند |

پورت API Mihomo فقط روی `127.0.0.1:19090` است و به اینترنت باز نمی‌شود. SOCKSها نیز فقط روی localhost هستند.
