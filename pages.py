LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🪐 ورود · پنل عقاب</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.19.0/dist/tabler-icons.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0a0a1a;--card:rgba(10,10,30,0.75);--card-b:rgba(100,80,255,0.12);--accent:#7C6BFF;--t1:#F0EEFF;--t2:#8888BB;--t3:#555577;--border:rgba(100,80,255,0.08)}
body{font-family:'Vazirmatn',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#0a0a1a,#1a0a2a,#0a0a2a);padding:20px;color:var(--t1)}
.container{max-width:400px;width:100%;background:var(--card);backdrop-filter:blur(30px);border-radius:24px;border:1px solid var(--border);padding:40px;box-shadow:0 25px 80px rgba(0,0,0,0.6)}
.brand{display:flex;align-items:center;gap:12px;margin-bottom:32px}
.brand-icon{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#7C6BFF,#5B4BD9,#A78BFA);display:flex;align-items:center;justify-content:center;font-size:22px}
.brand-text{font-size:16px;font-weight:800;background:linear-gradient(135deg,#A78BFA,#7C6BFF);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.brand-sub{font-size:9px;color:var(--t3)}
.welcome{font-size:22px;font-weight:800;color:var(--t1);margin-bottom:4px}
.sub-text{font-size:13px;color:var(--t3);margin-bottom:28px}
.field{margin-bottom:18px}
.field label{display:block;font-size:10px;font-weight:600;color:var(--t2);margin-bottom:4px}
.field input{width:100%;padding:12px 14px;border-radius:10px;border:1px solid var(--border);background:rgba(0,0,20,.3);color:var(--t1);font-family:inherit;font-size:14px;outline:none;transition:.3s}
.field input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(100,80,255,.08)}
.options{display:flex;justify-content:space-between;align-items:center;margin:14px 0 20px;font-size:12px}
.options label{display:flex;align-items:center;gap:6px;color:var(--t2);cursor:pointer}
.btn-login{width:100%;padding:12px;border-radius:10px;border:none;cursor:pointer;background:linear-gradient(135deg,#7C6BFF,#5B4BD9,#A78BFA);color:#fff;font-family:inherit;font-size:15px;font-weight:700;transition:all .3s}
.btn-login:hover{transform:translateY(-2px);box-shadow:0 8px 40px rgba(100,80,255,.35)}
.btn-login:disabled{opacity:.5;cursor:not-allowed;transform:none}
.error-box{display:none;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.15);border-radius:8px;padding:10px 12px;margin-bottom:14px;font-size:12px;color:#F87171;align-items:center;gap:8px}
.error-box.show{display:flex}
#workspace-field{display:none}
select{width:100%;padding:12px 14px;border-radius:10px;border:1px solid var(--border);background:rgba(0,0,20,.3);color:var(--t1);font-family:inherit;font-size:14px;outline:none}
</style>
</head>
<body>
<div class="container">
    <div class="brand"><div class="brand-icon">🪐</div><div><div class="brand-text">پنل عقاب</div><div class="brand-sub">مدیریت کاربران</div></div></div>
    <div class="welcome" id="welcome-text">خوش آمدید</div>
    <div class="sub-text" id="sub-text">وارد حساب کاربری خود شوید</div>
    <div class="error-box" id="error-box"><i class="ti ti-alert-circle"></i><span id="error-text"></span></div>
    <form id="login-form" onsubmit="handleLogin(event)">
        <div class="field"><label id="label-username">نام کاربری</label><input type="text" id="username" placeholder="نام کاربری" value="admin" dir="ltr"></div>
        <div class="field"><label id="label-password">رمز عبور</label><input type="password" id="password" placeholder="رمز عبور را وارد کنید" dir="ltr"></div>
        <div class="field" id="workspace-field"><label id="label-workspace">فضای کاری</label><select id="workspace-select"><option value="">انتخاب کنید...</option></select></div>
        <div class="options"><label><input type="checkbox" id="remember"> <span id="remember-text">مرا به خاطر بسپار</span></label></div>
        <button class="btn-login" type="submit" id="login-btn"><i class="ti ti-login-2"></i> <span id="login-text">ورود</span></button>
    </form>
</div>
<script>
const translations={fa:{welcome:"خوش آمدید",sub:"وارد حساب کاربری خود شوید",username:"نام کاربری",password:"رمز عبور",workspace:"فضای کاری",remember:"مرا به خاطر بسپار",login:"ورود"},en:{welcome:"Welcome Back",sub:"Login to your account",username:"Username",password:"Password",workspace:"Workspace",remember:"Remember me",login:"Login"}};
let currentLang=localStorage.getItem('eagle-lang')||'fa';
function setLang(lang){currentLang=lang;localStorage.setItem('eagle-lang',lang);updateTexts()}
function updateTexts(){const t=translations[currentLang];document.getElementById('welcome-text').textContent=t.welcome;document.getElementById('sub-text').textContent=t.sub;document.getElementById('label-username').textContent=t.username;document.getElementById('label-password').textContent=t.password;document.getElementById('label-workspace').textContent=t.workspace;document.getElementById('remember-text').textContent=t.remember;document.getElementById('login-text').textContent=t.login}
async function loadWorkspaces(){try{const r=await fetch('/api/admin/workspaces');if(r.ok){const data=await r.json();const sel=document.getElementById('workspace-select');sel.innerHTML='<option value="">انتخاب کنید...</option>';data.workspaces.forEach(ws=>{const opt=document.createElement('option');opt.value=ws.id;opt.textContent=ws.name+' ('+ws.admin_username+')';if(ws.is_quota_exceeded){opt.textContent+=' ⛔'}sel.appendChild(opt)});document.getElementById('workspace-field').style.display='block'}}catch(e){}}
async function handleLogin(e){e.preventDefault();const btn=document.getElementById('login-btn');const err=document.getElementById('error-box');const errText=document.getElementById('error-text');err.classList.remove('show');btn.disabled=true;btn.innerHTML='⏳ در حال ورود...';try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value,workspace_id:document.getElementById('workspace-select').value,remember:document.getElementById('remember').checked})});const data=await r.json();if(!r.ok){errText.textContent=data.detail||'نام کاربری یا رمز عبور اشتباه است';err.classList.add('show');btn.disabled=false;btn.innerHTML='🚪 '+translations[currentLang].login;return}window.location.href='/dashboard'}catch(e){errText.textContent='خطا در ارتباط با سرور';err.classList.add('show');btn.disabled=false;btn.innerHTML='🚪 '+translations[currentLang].login}}
document.addEventListener('DOMContentLoaded',async()=>{setLang(currentLang);await loadWorkspaces();try{const r=await fetch('/api/me');const d=await r.json();if(d.authenticated){window.location.href='/dashboard'}}catch(e){}});
</script>
</body></html>"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🪐 پنل عقاب</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.19.0/dist/tabler-icons.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0a0a1a;--card:rgba(10,10,30,0.7);--card-b:rgba(100,80,255,0.08);--accent:#7C6BFF;--t1:#F0EEFF;--t2:#8888BB;--t3:#555577;--sidebar-w:180px;--radius:12px;--shadow:0 8px 32px rgba(0,0,0,0.5)}
body{font-family:'Vazirmatn',sans-serif;background:var(--bg);color:var(--t1);min-height:100vh;display:flex;font-size:13px}
.sidebar{width:var(--sidebar-w);min-height:100vh;background:var(--card);backdrop-filter:blur(30px);border-left:1px solid var(--card-b);display:flex;flex-direction:column;flex-shrink:0;position:fixed;right:0;top:0;bottom:0;z-index:200}
.logo{display:flex;align-items:center;gap:10px;padding:16px 12px;border-bottom:1px solid var(--card-b)}
.logo-icon{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#7C6BFF,#5B4BD9,#A78BFA);display:flex;align-items:center;justify-content:center;font-size:18px}
.logo-name{font-size:13px;font-weight:800;background:linear-gradient(135deg,#A78BFA,#7C6BFF);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.logo-sub{font-size:7px;color:var(--t3)}
.nav-wrap{flex:1;overflow-y:auto;padding:6px 0}
.nav-it{display:flex;align-items:center;gap:8px;padding:8px 10px;color:var(--t3);font-size:11px;cursor:pointer;border-right:2px solid transparent;transition:all .2s;margin:1px 4px;border-radius:6px}
.nav-it i{font-size:14px;width:18px}
.nav-it:hover{background:rgba(100,80,255,0.05);color:var(--t2)}
.nav-it.on{background:rgba(100,80,255,0.08);color:var(--t1);border-right-color:var(--accent);font-weight:600}
.sb-foot{padding:10px 12px;border-top:1px solid var(--card-b)}
.logout-btn{display:flex;align-items:center;justify-content:center;gap:6px;background:rgba(239,68,68,0.08);color:#F87171;border-radius:6px;padding:6px;font-size:10px;font-weight:500;font-family:inherit;border:1px solid rgba(239,68,68,0.1);cursor:pointer;width:100%;transition:.2s}
.logout-btn:hover{background:rgba(239,68,68,0.15)}
.main{margin-right:var(--sidebar-w);flex:1;padding:16px 20px 80px;min-width:0}
.pg{display:none}.pg.on{display:block}
.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:8px}
.tb-title{font-size:17px;font-weight:800;color:var(--t1);display:flex;align-items:center;gap:6px}
.tb-title i{color:var(--accent)}
.tb-sub{font-size:10px;color:var(--t3)}
.btn{font-family:inherit;font-size:10px;font-weight:600;border-radius:6px;padding:5px 10px;cursor:pointer;display:inline-flex;align-items:center;gap:4px;border:none;transition:all .2s}
.btn-p{background:linear-gradient(135deg,#7C6BFF,#5B4BD9,#A78BFA);color:#fff;box-shadow:0 3px 15px rgba(100,80,255,.2)}
.btn-p:hover{transform:translateY(-1px);box-shadow:0 6px 25px rgba(100,80,255,.3)}
.btn-o{background:rgba(255,255,255,0.02);border:1px solid var(--card-b);color:var(--t2)}
.btn-o:hover{background:rgba(100,80,255,0.05)}
.btn-sm{padding:2px 6px;font-size:8px;border-radius:4px}
.btn-d{background:rgba(239,68,68,0.08);color:#F87171;border:1px solid rgba(239,68,68,0.1)}
.btn-d:hover{background:rgba(239,68,68,0.15)}
.btn-pur{background:rgba(100,80,255,0.08);color:var(--accent);border:1px solid rgba(100,80,255,.1)}
.btn-pur:hover{background:rgba(100,80,255,0.15)}
.btn-amber{background:rgba(245,158,11,0.08);color:#F59E0B;border:1px solid rgba(245,158,11,0.1)}
.btn-amber:hover{background:rgba(245,158,11,0.15)}
.badge{font-size:8px;padding:2px 8px;border-radius:12px;font-weight:700;display:inline-flex;align-items:center;gap:3px}
.bg-fire{background:rgba(100,80,255,0.08);color:#A78BFA}
.dot{width:5px;height:5px;border-radius:50%;display:inline-block}
.dg{background:#10B981}
.stats-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:16px}
.stat-card{background:var(--card);backdrop-filter:blur(20px);border:1px solid var(--card-b);border-radius:var(--radius);padding:12px 8px;text-align:center}
.stat-card .icon{font-size:18px;display:block;margin-bottom:3px}
.stat-card .number{font-size:18px;font-weight:800;color:var(--t1)}
.stat-card .label{font-size:9px;color:var(--t3);margin-top:2px}
.stat-card .sub{font-size:7px;color:var(--t3);opacity:.6}
.stat-mini{background:var(--card);border:1px solid var(--card-b);border-radius:8px;padding:8px 12px;display:flex;align-items:center;gap:8px}
.stat-mini-icon{font-size:16px}
.stat-mini-num{font-size:16px;font-weight:800;color:var(--t1)}
.stat-mini-label{font-size:9px;color:var(--t3)}
.users-table{width:100%;border-collapse:collapse;font-size:12px}
.users-table thead th{padding:10px 12px;text-align:right;color:var(--t2);font-size:9px;font-weight:700;text-transform:uppercase;border-bottom:1px solid var(--card-b);background:rgba(100,80,255,0.02)}
.users-table tbody td{padding:8px 12px;border-bottom:1px solid var(--card-b);color:var(--t1)}
.users-table tbody tr:hover{background:rgba(100,80,255,0.02)}
.users-table .status-badge{display:inline-flex;align-items:center;gap:5px;padding:2px 10px;border-radius:12px;font-size:9px;font-weight:700}
.users-table .status-badge.active{background:rgba(16,185,129,0.08);color:#10B981}
.users-table .status-badge.expired{background:rgba(239,68,68,0.08);color:#EF4444}
.users-table .status-badge.disabled{background:rgba(245,158,11,0.08);color:#F59E0B}
.users-table .usage-bar{display:flex;align-items:center;gap:6px}
.users-table .usage-bar .bar{width:80px;height:3px;border-radius:3px;background:rgba(100,80,255,0.05);overflow:hidden}
.users-table .usage-bar .bar .fill{height:100%;border-radius:3px;background:linear-gradient(90deg,#7C6BFF,#5B4BD9,#A78BFA)}
.users-table .usage-text{font-size:9px;color:var(--t2)}
.users-table .action-btns{display:flex;gap:3px;justify-content:center}
.users-table .action-btns .btn{padding:2px 6px;font-size:8px;border-radius:4px}
.user-name-cell{display:flex;align-items:center;gap:6px}
.user-name-cell .avatar{width:24px;height:24px;border-radius:6px;background:linear-gradient(135deg,#7C6BFF,#5B4BD9);display:flex;align-items:center;justify-content:center;font-size:10px;color:#fff}
.user-name-cell .name{font-weight:600;color:var(--t1)}
.user-name-cell .uuid-short{font-size:7px;color:var(--t3);font-family:monospace}
.settings-card{background:var(--card);border:1px solid var(--card-b);border-radius:var(--radius);padding:14px 16px;max-width:480px;margin-bottom:10px}
.settings-card .title{font-size:13px;font-weight:700;color:var(--t1);margin-bottom:10px;display:flex;align-items:center;gap:6px}
.settings-card .title i{color:var(--accent)}
.settings-card .field{margin-bottom:8px}
.settings-card .field label{font-size:9px;color:var(--t3);display:block;margin-bottom:2px;font-weight:600}
.settings-card .field input{width:100%;padding:6px 10px;border-radius:6px;border:1px solid var(--card-b);background:rgba(0,0,20,.2);color:var(--t1);font-family:inherit;font-size:11px;outline:none;transition:.2s}
.settings-card .field input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(100,80,255,.06)}
.settings-card .btn{width:100%;justify-content:center;margin-top:3px;font-size:11px;padding:6px}
.settings-card .toggle-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--card-b)}
.switch{position:relative;width:36px;height:20px;background:var(--t3);border-radius:10px;cursor:pointer;transition:.3s;flex-shrink:0}
.switch.on{background:linear-gradient(135deg,#7C6BFF,#5B4BD9)}
.switch .slider{position:absolute;top:2px;right:2px;width:16px;height:16px;background:#fff;border-radius:50%;transition:.3s}
.switch.on .slider{right:18px}
.toast{position:fixed;bottom:70px;left:50%;transform:translateX(-50%) translateY(50px);background:var(--card);border:1px solid var(--card-b);color:var(--t1);border-radius:8px;padding:8px 16px;font-size:11px;opacity:0;transition:all .3s;z-index:999;pointer-events:none}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.toast.ok{border-color:rgba(16,185,129,.2);color:#10B981}
.toast.err{border-color:rgba(239,68,68,.2);color:#EF4444}
.empty{text-align:center;padding:30px 15px;color:var(--t3)}
.empty i{font-size:28px;opacity:.3;display:block}
.fi{width:100%;padding:6px 10px;border-radius:6px;border:1px solid var(--card-b);background:rgba(0,0,20,.2);color:var(--t1);font-family:inherit;font-size:10px;outline:none;transition:.2s}
.fi:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(100,80,255,.06)}
select.fi{appearance:none;cursor:pointer}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:500;align-items:center;justify-content:center;backdrop-filter:blur(8px)}
.modal-bg.open{display:flex}
.modal{background:var(--card);border:1px solid var(--card-b);border-radius:14px;padding:20px 18px;max-width:520px;width:calc(100% - 20px);max-height:90vh;overflow-y:auto;position:relative;box-shadow:var(--shadow)}
.modal-close{position:absolute;top:10px;left:10px;background:rgba(100,80,255,0.05);border:1px solid var(--card-b);color:var(--t2);width:24px;height:24px;border-radius:6px;font-size:12px;display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;transition:.2s}
.modal-close:hover{background:rgba(239,68,68,0.08);color:#EF4444}
.modal-title{font-size:14px;font-weight:700;color:var(--t1);margin-bottom:12px;display:flex;align-items:center;gap:6px}
.fg{display:flex;flex-direction:column;gap:2px;margin-bottom:8px}
.fg label{font-size:8px;color:var(--t3);font-weight:700;text-transform:uppercase;display:flex;align-items:center;gap:3px}
</style>
</head>
<body>
<div class="sidebar">
  <div class="logo"><div class="logo-icon">🪐</div><div><div class="logo-name">پنل عقاب</div><div class="logo-sub">مدیریت کاربران</div></div></div>
  <div class="nav-wrap">
    <div class="nav-it on" data-pg="dashboard"><i class="ti ti-layout-dashboard"></i> خانه</div>
    <div class="nav-it" data-pg="users"><i class="ti ti-users"></i> کاربران</div>
    <div class="nav-it" data-pg="settings"><i class="ti ti-settings"></i> تنظیمات</div>
    <div class="nav-it" data-pg="workspace"><i class="ti ti-buildings"></i> Workspace</div>
  </div>
  <div class="sb-foot"><button class="logout-btn" onclick="logout()"><i class="ti ti-logout"></i> خروج</button></div>
</div>
<div class="main">
<!-- ===== خانه ===== -->
<section class="pg on" id="pg-dashboard">
  <div class="topbar">
    <div><div class="tb-title"><i class="ti ti-layout-dashboard"></i> خانه</div><div class="tb-sub" id="last-update">بروزرسانی: لحظه‌ای</div></div>
    <div class="tb-right">
      <span class="badge bg-fire" id="online-badge"><span class="dot dg"></span> ۰ آنلاین</span>
      <button class="btn btn-p btn-sm" onclick="openModal('modal-user')"><i class="ti ti-plus"></i> کاربر</button>
    </div>
  </div>
  <div class="stats-grid">
    <div class="stat-card"><span class="icon">📊</span><div class="number" id="stat-traffic">۰</div><div class="label">ترافیک</div><div class="sub">MB</div></div>
    <div class="stat-card"><span class="icon">📨</span><div class="number" id="stat-requests">۰</div><div class="label">درخواست‌ها</div><div class="sub">تعداد</div></div>
    <div class="stat-card"><span class="icon">⏱️</span><div class="number" id="stat-uptime">۰۰:۰۰:۰۰</div><div class="label">آپتایم</div><div class="sub">زمان</div></div>
    <div class="stat-card"><span class="icon">💾</span><div class="number" id="stat-disk">۰ GB</div><div class="label">فضای دیسک</div><div class="sub" id="stat-disk-used">استفاده</div></div>
    <div class="stat-card"><span class="icon">📶</span><div class="number" id="stat-speed">۰ B/s</div><div class="label">سرعت</div><div class="sub">لحظه‌ای</div></div>
    <div class="stat-card"><span class="icon">👥</span><div class="number" id="stat-users">۰</div><div class="label">کاربران</div><div class="sub" id="stat-users-active">۰ فعال</div></div>
  </div>
</section>

<!-- ===== کاربران ===== -->
<section class="pg" id="pg-users">
  <div class="topbar">
    <div><div class="tb-title"><i class="ti ti-users"></i> کاربران</div><div class="tb-sub" id="users-sub">لیست کانفیگ‌ها، سهمیه و انقضا</div></div>
    <div class="tb-right"><button class="btn btn-o btn-sm" onclick="loadUsers()"><i class="ti ti-refresh"></i></button></div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px;">
    <div class="stat-mini"><span class="stat-mini-icon">👥</span><span class="stat-mini-num" id="users-total">0</span><span class="stat-mini-label">کل کاربران</span></div>
    <div class="stat-mini"><span class="stat-mini-icon">🟢</span><span class="stat-mini-num" id="users-active">0</span><span class="stat-mini-label">فعال</span></div>
    <div class="stat-mini"><span class="stat-mini-icon">🔴</span><span class="stat-mini-num" id="users-expired">0</span><span class="stat-mini-label">منقضی</span></div>
    <div class="stat-mini"><span class="stat-mini-icon">📊</span><span class="stat-mini-num" id="users-traffic">0</span><span class="stat-mini-label">مصرف کل</span></div>
  </div>
  <div style="background:var(--card);border:1px solid var(--card-b);border-radius:var(--radius);overflow:hidden;">
    <div style="overflow-x:auto;">
      <table class="users-table">
        <thead><tr><th>نام</th><th>وضعیت</th><th>مصرف</th><th>مدت</th><th style="text-align:center;">عملیات</th></tr></thead>
        <tbody id="users-tbody"><tr><td colspan="5" style="text-align:center;padding:30px;color:var(--t3);">هیچ کاربری وجود ندارد</td></tr></tbody>
      </table>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-top:1px solid var(--card-b);flex-wrap:wrap;gap:8px;">
      <div style="font-size:9px;color:var(--t3);"><span id="users-count-label">۰ کاربر</span></div>
      <button class="btn btn-p btn-sm" onclick="openModal('modal-user')"><i class="ti ti-plus"></i> افزودن کاربر جدید</button>
    </div>
  </div>
</section>

<!-- ===== تنظیمات ===== -->
<section class="pg" id="pg-settings">
  <div class="topbar"><div><div class="tb-title"><i class="ti ti-settings"></i> تنظیمات</div><div class="tb-sub">مدیریت پنل</div></div></div>
  
  <div class="settings-card">
    <div class="title"><i class="ti ti-buildings"></i> تنظیمات حساب کاربری</div>
    <div class="field"><label>نام کاربری جدید</label><input class="fi" id="ws-new-username" placeholder="نام کاربری جدید"></div>
    <button class="btn btn-pur" onclick="changeWorkspaceUsername()" style="width:100%;"><i class="ti ti-user"></i> تغییر نام کاربری</button>
    <div id="ws-username-result" style="margin-top:6px;display:none;font-size:11px;"></div>
    <div style="border-top:1px solid var(--card-b);margin:10px 0;"></div>
    <div class="field"><label>رمز فعلی</label><input class="fi" id="ws-old-password" type="password" placeholder="رمز فعلی"></div>
    <div class="field"><label>رمز جدید</label><input class="fi" id="ws-new-password" type="password" placeholder="حداقل ۴ کاراکتر"></div>
    <div class="field"><label>تکرار</label><input class="fi" id="ws-confirm-password" type="password" placeholder="تکرار"></div>
    <button class="btn btn-p" onclick="changeWorkspacePassword()" style="width:100%;"><i class="ti ti-key"></i> تغییر رمز</button>
    <div id="ws-password-result" style="margin-top:6px;display:none;font-size:11px;"></div>
  </div>
  
  <div class="settings-card">
    <div class="title"><i class="ti ti-server"></i> IP تمیز</div>
    <div id="clean-ips-list" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;"></div>
    <div style="display:flex;gap:6px;">
      <input class="fi" id="clean-ip-input" placeholder="مثلاً: 104.16.5.10" style="flex:2;">
      <select class="fi" id="clean-ip-provider" style="flex:1;"><option value="MCI">MCI</option><option value="Irancell">Irancell</option><option value="Hamrahe Aval">Hamrahe Aval</option></select>
      <button class="btn btn-p btn-sm" onclick="addCleanIP()"><i class="ti ti-plus"></i></button>
    </div>
  </div>
  
  <div class="settings-card">
    <div class="title"><i class="ti ti-filter"></i> فیلتر محتوا</div>
    <div class="toggle-row"><div class="toggle-label">🚫 فیلتر تبلیغات</div><div class="switch" id="ad-filter-switch" onclick="toggleFilter('ad')"><div class="slider"></div></div></div>
    <div class="toggle-row"><div class="toggle-label">🔞 فیلتر بزرگسالان</div><div class="switch" id="porn-filter-switch" onclick="toggleFilter('porn')"><div class="slider"></div></div></div>
    <div class="toggle-row"><div class="toggle-label">🛡️ فیلتر بدافزار</div><div class="switch" id="malware-filter-switch" onclick="toggleFilter('malware')"><div class="slider"></div></div></div>
  </div>
  
  <div class="settings-card">
    <div class="title"><i class="ti ti-route"></i> مسیرها</div>
    <div id="routes-list" style="margin-bottom:8px;"></div>
    <div style="display:flex;gap:6px;">
      <input class="fi" id="route-domain" placeholder="دامنه" style="flex:1;">
      <select class="fi" id="route-type" style="flex:1;"><option value="direct">مستقیم</option><option value="proxy">پروکسی</option><option value="block">بلاک</option></select>
      <button class="btn btn-p btn-sm" onclick="addRoute()"><i class="ti ti-plus"></i></button>
    </div>
  </div>
</section>

<!-- ===== Workspace ===== -->
<section class="pg" id="pg-workspace">
  <div class="topbar"><div><div class="tb-title"><i class="ti ti-buildings"></i> مدیریت Workspace</div><div class="tb-sub">مدیریت فضاهای کاری</div></div>
    <div class="tb-right"><button class="btn btn-p btn-sm" onclick="openModal('modal-workspace')"><i class="ti ti-plus"></i> جدید</button></div>
  </div>
  <div id="workspaces-container" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;"></div>
</section>
</div>

<!-- ===== مودال ساخت کاربر ===== -->
<div class="modal-bg" id="modal-user">
  <div class="modal">
    <button class="modal-close" onclick="closeModal('modal-user')"><i class="ti ti-x"></i></button>
    <div class="modal-title"><i class="ti ti-user-plus"></i> ساخت کاربر جدید</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
      <div class="fg" style="grid-column:1/2;"><label>نام کاربری</label><input class="fi" id="user-label" placeholder="مثلاً: علی" value="کاربر"></div>
      <div class="fg"><label>حجم (GB)</label><input class="fi" id="user-quota" type="number" min="0.5" step="0.5" value="2"></div>
      <div class="fg"><label>انقضا (روز)</label><input class="fi" id="user-exp" type="number" min="0" value="30"></div>
      <div class="fg"><label>دستگاه</label><input class="fi" id="user-devices" type="number" min="0" max="10" value="1"></div>
    </div>
    <div class="fg"><label>فینگرپرینت</label>
      <select class="fi" id="user-fingerprint"><option value="chrome">🌐 Chrome</option><option value="firefox">🦊 Firefox</option><option value="safari">🧭 Safari</option><option value="edge">🌊 Edge</option><option value="ios">📱 iOS</option><option value="android">🤖 Android</option><option value="random">🎲 Random</option><option value="none">🚫 None</option></select>
    </div>
    <div class="fg"><label>IP تمیز</label><input class="fi" id="user-clean-ip" placeholder="مثلاً: 104.16.5.10"></div>
    <div class="fg"><label>رمز (اختیاری)</label><input class="fi" id="user-password" type="password" placeholder="برای ویرایش/حذف"></div>
    <div style="display:flex;gap:6px;margin-top:10px">
      <button class="btn btn-p" onclick="saveUser()" style="flex:2"><i class="ti ti-check"></i> ساخت</button>
      <button class="btn btn-o" onclick="closeModal('modal-user')" style="flex:1">انصراف</button>
    </div>
  </div>
</div>

<!-- ===== مودال Workspace ===== -->
<div class="modal-bg" id="modal-workspace">
  <div class="modal">
    <button class="modal-close" onclick="closeModal('modal-workspace')"><i class="ti ti-x"></i></button>
    <div class="modal-title"><i class="ti ti-buildings"></i> ساخت Workspace جدید</div>
    <div class="fg"><label>نام</label><input class="fi" id="ws-name-input" placeholder="مثلاً: شرکت الف"></div>
    <div class="fg"><label>نام کاربری ادمین</label><input class="fi" id="ws-admin-username" placeholder="نام کاربری"></div>
    <div class="fg"><label>رمز عبور</label><input class="fi" id="ws-admin-password" type="password" placeholder="حداقل ۴ کاراکتر"></div>
    <div class="fg"><label>سهمیه (GB)</label><input class="fi" id="ws-quota-input" type="number" min="0" value="50"></div>
    <div style="display:flex;gap:6px;margin-top:10px">
      <button class="btn btn-p" onclick="saveWorkspace()" style="flex:2"><i class="ti ti-check"></i> ساخت</button>
      <button class="btn btn-o" onclick="closeModal('modal-workspace')" style="flex:1">انصراف</button>
    </div>
  </div>
</div>

<script>
const toast=(m,t='')=>{const e=document.getElementById('toast');e.textContent=m;e.className='toast show'+(t?' '+t:'');setTimeout(()=>e.classList.remove('show'),2500)};
const fmtB=b=>{if(!b||b==0)return'0 B';if(b<1024)return b+' B';if(b<1024**2)return(b/1024).toFixed(1)+' KB';if(b<1024**3)return(b/1024**2).toFixed(1)+' MB';if(b<1024**4)return(b/1024**3).toFixed(2)+' GB';return(b/1024**4).toFixed(2)+' TB'};
const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const openModal=id=>document.getElementById(id).classList.add('open');
const closeModal=id=>document.getElementById(id).classList.remove('open');
let isMainAdmin=false;

async function authF(url,opts={}){const r=await fetch(url,opts);if(r.status===401){location.href='/login';throw new Error()}return r}
async function logout(){try{await fetch('/api/logout',{method:'POST'})}catch(e){}location.href='/login'}

function navTo(name){
  document.querySelectorAll('.nav-it').forEach(n=>n.classList.toggle('on',n.dataset.pg===name));
  document.querySelectorAll('.pg').forEach(p=>p.classList.toggle('on',p.id==='pg-'+name));
  const loaders={dashboard:loadDashboard,users:loadUsers,settings:loadSettings,workspace:loadWorkspaces};
  if(loaders[name])loaders[name]()
}
document.querySelectorAll('.nav-it').forEach(el=>el.addEventListener('click',()=>navTo(el.dataset.pg)));

async function checkUserType(){
  try{const r=await fetch('/api/me');const d=await r.json();isMainAdmin=d.is_main_admin||false;document.querySelector('[data-pg="workspace"]').style.display=isMainAdmin?'block':'none'}catch(e){}
}

async function loadDashboard(){
  try{
    const r=await authF('/api/dashboard/stats');const d=await r.json();
    document.getElementById('stat-traffic').textContent=(d.traffic.total/(1024*1024)).toFixed(1);
    document.getElementById('stat-requests').textContent=d.requests||0;
    document.getElementById('stat-uptime').textContent=d.uptime||'00:00:00';
    document.getElementById('stat-disk').textContent=d.disk.total_fmt||'0 GB';
    document.getElementById('stat-disk-used').textContent='استفاده: '+(d.disk.used_fmt||'0');
    document.getElementById('stat-speed').textContent=d.speed.download_fmt||'0 B/s';
    document.getElementById('stat-users').textContent=d.links_count||0;
    document.getElementById('stat-users-active').textContent=(d.active_links||0)+' فعال';
    document.getElementById('online-badge').innerHTML='<span class="dot dg"></span> '+(d.connections||0)+' آنلاین';
  }catch(e){}
}

async function loadUsers(){
  try{
    const r=await authF('/api/workspace/links');const{links=[]}=await r.json();const tbody=document.getElementById('users-tbody');
    document.getElementById('users-total').textContent=links.length;
    document.getElementById('users-active').textContent=links.filter(l=>l.active&&!l.expired).length;
    document.getElementById('users-expired').textContent=links.filter(l=>l.expired).length;
    document.getElementById('users-traffic').textContent=fmtB(links.reduce((s,l)=>s+(l.used_bytes||0),0));
    document.getElementById('users-count-label').textContent=links.length+' کاربر';
    if(!links.length){tbody.innerHTML='<tr><td colspan="5" style="text-align:center;padding:30px;color:var(--t3);">هیچ کاربری وجود ندارد</td></tr>';return}
    const fpEmoji={chrome:'🌐',firefox:'🦊',safari:'🧭',edge:'🌊',ios:'📱',android:'🤖',random:'🎲',none:'🚫'};
    tbody.innerHTML=links.map(l=>{
      const active=l.active&&!l.expired;
      const statusClass=active?'active':l.expired?'expired':'disabled';
      const statusText=active?'فعال':l.expired?'منقضی':'غیرفعال';
      const pct=l.limit_bytes===0?0:Math.min(100,(l.used_bytes/l.limit_bytes)*100);
      let dur='∞';if(l.expires_at){try{const d=Math.ceil((new Date(l.expires_at)-new Date())/(1000*60*60*24));dur=d>0?d+' روز':'منقضی'}catch(e){}}
      return `<tr>
        <td><div class="user-name-cell"><div class="avatar">${(l.label||'U')[0].toUpperCase()}</div><div><div class="name">${esc(l.label)}</div><div class="uuid-short">${l.uuid.slice(0,8)}…</div></div></div></td>
        <td><span class="status-badge ${statusClass}">${statusText}</span></td>
        <td><div class="usage-bar"><span class="usage-text">${fmtB(l.used_bytes||0)} / ${l.limit_bytes===0?'∞':fmtB(l.limit_bytes)}</span><div class="bar"><div class="fill" style="width:${pct}%"></div></div></div></td>
        <td style="font-size:10px;color:var(--t2);">${dur}</td>
        <td><div class="action-btns">
          <button class="btn btn-o btn-sm" onclick="navigator.clipboard.writeText('${esc(l.vless_link)}').then(()=>toast('✅ کپی','ok'))"><i class="ti ti-copy"></i></button>
          <button class="btn btn-pur btn-sm" onclick="openEditModal('${l.uuid}')"><i class="ti ti-edit"></i></button>
          <button class="btn btn-d btn-sm" onclick="openDeleteModal('${l.uuid}')"><i class="ti ti-trash"></i></button>
        </div></td>
      </tr>`
    }).join('')
  }catch(e){console.error(e)}
}

async function saveUser(){
  const label=document.getElementById('user-label').value.trim()||'کاربر';
  const quota=parseFloat(document.getElementById('user-quota').value)||0;
  const exp=parseInt(document.getElementById('user-exp').value)||30;
  const devices=parseInt(document.getElementById('user-devices').value)||0;
  const password=document.getElementById('user-password').value.trim();
  const fingerprint=document.getElementById('user-fingerprint').value||'chrome';
  const clean_ip=document.getElementById('user-clean-ip').value.trim()||null;
  try{
    const r=await authF('/api/workspace/links',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label,limit_value:quota,limit_unit:'GB',expires_days:exp,max_devices:devices,password,fingerprint,protocol:'vless-ws',ports:[443],clean_ip})});
    if(!r.ok){toast('❌ خطا','err');return}
    closeModal('modal-user');toast('✅ کاربر ساخته شد','ok');loadUsers();loadDashboard()
  }catch(e){toast('❌ خطا','err')}
}

async function changeWorkspaceUsername(){
  const newUser=document.getElementById('ws-new-username').value.trim();const res=document.getElementById('ws-username-result');
  if(!newUser||newUser.length<3){res.style.display='block';res.style.color='#EF4444';res.innerHTML='❌ حداقل ۳ کاراکتر';return}
  try{const r=await authF('/api/workspace/change-username',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({new_username:newUser})});const d=await r.json();if(!r.ok){res.style.display='block';res.style.color='#EF4444';res.innerHTML='❌ '+d.detail;return}res.style.display='block';res.style.color='#10B981';res.innerHTML='✅ تغییر کرد';toast('✅ تغییر کرد','ok')}catch(e){res.style.display='block';res.style.color='#EF4444';res.innerHTML='❌ خطا'}
}

async function changeWorkspacePassword(){
  const old=document.getElementById('ws-old-password').value;
  const np=document.getElementById('ws-new-password').value;
  const cp=document.getElementById('ws-confirm-password').value;
  const res=document.getElementById('ws-password-result');
  if(!old||!np||!cp){res.style.display='block';res.style.color='#EF4444';res.innerHTML='❌ همه فیلدها را پر کنید';return}
  if(np.length<4){res.style.display='block';res.style.color='#EF4444';res.innerHTML='❌ حداقل ۴ کاراکتر';return}
  if(np!==cp){res.style.display='block';res.style.color='#EF4444';res.innerHTML='❌ رمزها مطابقت ندارند';return}
  try{const r=await authF('/api/workspace/change-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old_password:old,new_password:np})});const d=await r.json();if(!r.ok){res.style.display='block';res.style.color='#EF4444';res.innerHTML='❌ '+d.detail;return}res.style.display='block';res.style.color='#10B981';res.innerHTML='✅ تغییر کرد';toast('✅ تغییر کرد','ok')}catch(e){res.style.display='block';res.style.color='#EF4444';res.innerHTML='❌ خطا'}
}

async function addCleanIP(){
  const ip=document.getElementById('clean-ip-input').value.trim();if(!ip){toast('❌ IP را وارد کنید','err');return}
  const provider=document.getElementById('clean-ip-provider').value;
  try{const r=await authF('/api/workspace/clean-ips',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip,provider})});if(r.ok){document.getElementById('clean-ip-input').value='';toast('✅ اضافه شد','ok');loadSettings()}}catch(e){toast('❌ خطا','err')}
}

async function addRoute(){
  const domain=document.getElementById('route-domain').value.trim();if(!domain){toast('❌ دامنه را وارد کنید','err');return}
  const type=document.getElementById('route-type').value;
  try{const r=await authF('/api/workspace/routes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain,type})});if(r.ok){document.getElementById('route-domain').value='';toast('✅ اضافه شد','ok');loadSettings()}}catch(e){toast('❌ خطا','err')}
}

async function toggleFilter(type){
  const sw=document.getElementById(type+'-filter-switch');const enabled=!sw.classList.contains('on');
  try{const r=await authF('/api/workspace/filters',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({[type+'_filter_enabled']:enabled})});if(r.ok){sw.className='switch'+(enabled?' on':'');toast(enabled?'✅ فعال شد':'❌ غیرفعال شد','ok')}}catch(e){toast('❌ خطا','err')}
}

async function loadSettings(){
  try{const r=await authF('/api/workspace/settings');const d=await r.json();
    document.getElementById('clean-ips-list').innerHTML=(d.clean_ips||[]).map(ip=>`<span style="background:rgba(100,80,255,0.05);border-radius:4px;padding:2px 8px;font-size:9px;">${ip.ip} (${ip.provider}) <button onclick="deleteCleanIP('${ip.ip}')" style="background:none;border:none;color:#EF4444;cursor:pointer;">×</button></span>`).join('');
    document.getElementById('routes-list').innerHTML=(d.routes||[]).map(r=>`<div style="padding:4px 6px;border-bottom:1px solid var(--card-b);font-size:9px;display:flex;justify-content:space-between;"><span>${r.domain} → ${r.type}</span><button onclick="deleteRoute('${r.domain}')" style="background:none;border:none;color:#EF4444;cursor:pointer;">×</button></div>`).join('');
    document.getElementById('ad-filter-switch').className='switch'+(d.ad_filter_enabled?' on':'');
    document.getElementById('porn-filter-switch').className='switch'+(d.porn_filter_enabled?' on':'');
    document.getElementById('malware-filter-switch').className='switch'+(d.malware_filter_enabled?' on':'');
  }catch(e){}
}

async function deleteCleanIP(ip){if(!confirm('حذف؟'))return;try{await authF('/api/workspace/clean-ips/'+ip,{method:'DELETE'});toast('✅ حذف شد','ok');loadSettings()}catch(e){}}
async function deleteRoute(domain){if(!confirm('حذف؟'))return;try{await authF('/api/workspace/routes/'+domain,{method:'DELETE'});toast('✅ حذف شد','ok');loadSettings()}catch(e){}}

async function loadWorkspaces(){
  try{const r=await authF('/api/admin/workspaces');const d=await r.json();const c=document.getElementById('workspaces-container');
    if(!d.workspaces||!d.workspaces.length){c.innerHTML='<div class="empty"><i class="ti ti-buildings"></i><p>هیچ Workspace ای وجود ندارد</p></div>';return}
    c.innerHTML=d.workspaces.map(ws=>`
      <div class="settings-card" style="max-width:100%;">
        <div style="display:flex;justify-content:space-between;">
          <div><div style="font-size:13px;font-weight:700;">🏢 ${esc(ws.name)}</div><div style="font-size:9px;color:var(--t2);">👤 ${esc(ws.admin_username)}</div></div>
          <div style="font-size:11px;color:${ws.is_quota_exceeded?'#EF4444':'#10B981'};">${ws.is_quota_exceeded?'⛔ تمام شده':'✅ فعال'}</div>
        </div>
        <div style="margin:6px 0;"><div style="display:flex;justify-content:space-between;font-size:9px;color:var(--t2);"><span>سهمیه: ${ws.quota_used_gb.toFixed(1)} / ${ws.quota_limit_gb} GB</span><span>${ws.quota_percent}%</span></div>
        <div style="height:4px;background:rgba(100,80,255,0.05);border-radius:2px;overflow:hidden;"><div style="width:${Math.min(ws.quota_percent,100)}%;height:100%;background:${ws.quota_percent>90?'#EF4444':ws.quota_percent>70?'#F59E0B':'linear-gradient(90deg,#7C6BFF,#5B4BD9)'};border-radius:2px;"></div></div></div>
        <div style="display:flex;gap:4px;flex-wrap:wrap;"><button class="btn btn-pur btn-sm" onclick="editQuota('${ws.id}')">سهمیه</button><button class="btn btn-amber btn-sm" onclick="resetQuota('${ws.id}')">ریست</button><button class="btn btn-d btn-sm" onclick="deleteWs('${ws.id}')">حذف</button></div>
      </div>
    `).join('')
  }catch(e){}
}
async function editQuota(id){const q=prompt('سهمیه جدید به GB:');if(q===null)return;const quota=parseFloat(q);if(isNaN(quota)||quota<0){toast('❌ عدد معتبر','err');return}try{await authF(`/api/admin/workspaces/${id}/quota`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({quota_gb:quota})});toast('✅ تغییر کرد','ok');loadWorkspaces()}catch(e){}}
async function resetQuota(id){if(!confirm('ریست مصرف؟'))return;try{await authF(`/api/admin/workspaces/${id}/quota/reset`,{method:'POST'});toast('✅ ریست شد','ok');loadWorkspaces()}catch(e){}}
async function deleteWs(id){if(!confirm('حذف Workspace؟'))return;try{await authF(`/api/admin/workspaces/${id}`,{method:'DELETE'});toast('✅ حذف شد','ok');loadWorkspaces()}catch(e){}}
async function saveWorkspace(){
  const name=document.getElementById('ws-name-input').value.trim();
  const username=document.getElementById('ws-admin-username').value.trim();
  const password=document.getElementById('ws-admin-password').value.trim();
  const quota=parseFloat(document.getElementById('ws-quota-input').value)||0;
  if(!name||!username||!password){toast('❌ همه فیلدها را پر کنید','err');return}
  if(password.length<4){toast('❌ رمز حداقل 4 کاراکتر','err');return}
  try{const r=await authF('/api/admin/workspaces',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,admin_username:username,admin_password:password,quota_gb:quota})});if(r.ok){closeModal('modal-workspace');toast('✅ ساخته شد','ok');loadWorkspaces()}}catch(e){toast('❌ خطا','err')}
}

document.addEventListener('DOMContentLoaded',async()=>{
  try{const r=await fetch('/api/me');const d=await r.json();if(!d.authenticated)location.href='/login'}catch(e){location.href='/login'}
  await checkUserType();loadDashboard();loadUsers();loadSettings();if(isMainAdmin)loadWorkspaces();
  setInterval(()=>{if(document.getElementById('pg-dashboard').classList.contains('on'))loadDashboard();if(document.getElementById('pg-users').classList.contains('on'))loadUsers()},5000)
});
</script>
</body></html>"""

# ===== تابع صفحه ساب‌لینک =====
def get_sub_page_html(uuid: str, link: dict) -> str:
    from datetime import datetime
    used = link.get('used_bytes', 0)
    limit = link.get('limit_bytes', 0)
    active = link.get('active', True)
    expired = link.get('expired', False)
    label = link.get('label', 'کاربر')
    fingerprint = link.get('fingerprint', 'chrome')
    max_devices = link.get('max_devices', 0)
    ports = link.get('ports', [443])
    active_connections = link.get('active_connections', 0)
    active_connections_list = link.get('active_connections_list', [])
    last_connected = link.get('last_connected_at')
    clean_ip = link.get('clean_ip')
    user_ip = link.get('user_ip', 'نامشخص')
    days_left = link.get('days_left', 'نامحدود')
    vless_links = link.get('vless_links', [])
    vless_link = vless_links[0] if vless_links else ""
    sub_url = link.get('sub_url', '')
    is_allowed = active and not expired
    
    def fmt_bytes_local(b):
        if not b or b == 0: return '0 B'
        if b < 1024: return f'{b} B'
        if b < 1024**2: return f'{b/1024:.1f} KB'
        if b < 1024**3: return f'{b/1024**2:.2f} MB'
        if b < 1024**4: return f'{b/1024**3:.2f} GB'
        return f'{b/1024**4:.2f} TB'
    
    used_fmt = fmt_bytes_local(used)
    limit_fmt = 'نامحدود' if limit == 0 else fmt_bytes_local(limit)
    percent = 0 if limit == 0 else min(100, (used / limit) * 100)
    
    last_connected_text = "—"
    if last_connected:
        try:
            dt = datetime.fromisoformat(last_connected)
            last_connected_text = dt.strftime("%Y-%m-%d %H:%M")
        except:
            last_connected_text = last_connected[:16]
    
    conns_html = ""
    if active_connections > 0:
        conns_html = f"""
        <div style="background:rgba(100,80,255,0.02);border:1px solid rgba(100,80,255,0.04);border-radius:10px;padding:8px 10px;margin:8px 0">
            <div style="display:flex;align-items:center;gap:4px;margin-bottom:4px;font-size:9px;color:#8888BB">
                <span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:#34D399;animation:pulse 1.5s infinite"></span>
                <span style="font-weight:700;color:#34D399;font-size:9px">{active_connections} دستگاه متصل</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:3px">"""
        for conn in active_connections_list[:10]:
            ip = conn.get('ip', 'نامشخص')
            conns_html += f"""<span style="font-family:monospace;font-size:8px;background:rgba(100,80,255,0.04);border:1px solid rgba(100,80,255,0.04);padding:1px 6px;border-radius:3px;color:#8888BB">🔵 {ip}</span>"""
        if len(active_connections_list) > 10:
            conns_html += f"""<span style="font-family:monospace;font-size:8px;background:rgba(100,80,255,0.02);padding:1px 6px;border-radius:3px;color:#555577">+{len(active_connections_list)-10}</span>"""
        conns_html += "</div></div>"
    else:
        conns_html = f"""<div style="background:rgba(100,80,255,0.02);border:1px solid rgba(100,80,255,0.04);border-radius:10px;padding:6px 10px;margin:8px 0;text-align:center"><span style="font-size:9px;color:#555577">🔴 بدون اتصال فعال</span></div>"""
    
    clean_ip_html = f"<div class='info-item'><span class='info-label'><i class='ti ti-server'></i> IP تمیز</span><span class='info-value proto'>{clean_ip if clean_ip else '—'}</span></div>" if clean_ip else ""
    
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>🪐 {label}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.19.0/dist/tabler-icons.min.css">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.25}}}}
body{{font-family:'Vazirmatn',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;color:#F0EEFF;background:linear-gradient(135deg,#0a0a1a,#1a0a2a,#0a0a2a);}}
.stars-sub{{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}}
.star-sub{{position:absolute;border-radius:50%;background:#fff;animation:twinkleSub 4s ease-in-out infinite}}
@keyframes twinkleSub{{0%,100%{{opacity:0.1}}50%{{opacity:0.4}}}}
.glow-sub{{position:fixed;border-radius:50%;filter:blur(150px);z-index:0;pointer-events:none}}
.glow-sub1{{width:350px;height:350px;background:rgba(100,80,255,0.04);top:-120px;right:-60px;animation:glowFloat2 7s ease-in-out infinite}}
.glow-sub2{{width:250px;height:250px;background:rgba(167,139,250,0.03);bottom:-60px;left:-40px;animation-delay:2s;animation:glowFloat2 9s ease-in-out infinite reverse}}
@keyframes glowFloat2{{0%,100%{{transform:translate(0,0) scale(1)}}50%{{transform:translate(20px,-20px) scale(1.05)}}}}
.card{{position:relative;z-index:10;background:rgba(10,10,30,0.8);backdrop-filter:blur(30px);border:1px solid rgba(100,80,255,0.06);border-radius:20px;padding:24px 22px 20px;max-width:420px;width:100%;box-shadow:0 0 60px rgba(0,0,0,0.4),0 0 80px rgba(100,80,255,0.02);animation:cardIn 0.6s ease;}}
@keyframes cardIn{{from{{opacity:0;transform:translateY(20px) scale(0.97)}}to{{opacity:1;transform:translateY(0) scale(1)}}}}
.brand{{display:flex;align-items:center;gap:10px;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid rgba(100,80,255,0.04);}}
.brand-icon{{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#7C6BFF,#5B4BD9,#A78BFA);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;box-shadow:0 0 30px rgba(100,80,255,0.1);}}
.brand-text .name{{font-size:13px;font-weight:800;background:linear-gradient(135deg,#A78BFA,#7C6BFF);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.brand-text .sub{{font-size:7px;color:#555577;margin-top:0px}}
.user-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:2px}}
.user-name{{font-size:17px;font-weight:800;color:#F0EEFF;display:flex;align-items:center;gap:4px}}
.user-name .fire{{font-size:15px}}
.status{{display:inline-flex;align-items:center;gap:3px;padding:2px 10px;border-radius:12px;font-size:9px;font-weight:700;}}
.status.active{{background:rgba(100,80,255,0.12);color:#A78BFA;border:1px solid rgba(100,80,255,0.08);}}
.status.inactive{{background:rgba(239,68,68,0.12);color:#F87171;border:1px solid rgba(239,68,68,0.08);}}
.uuid-box{{background:rgba(100,80,255,0.02);border:1px solid rgba(100,80,255,0.04);border-radius:6px;padding:4px 8px;font-size:8px;font-family:monospace;color:#555577;word-break:break-all;margin:3px 0 8px;cursor:pointer;transition:.3s}}
.uuid-box:hover{{background:rgba(100,80,255,0.04);transform:scale(1.01)}}
.info-grid{{display:grid;gap:5px;margin:8px 0}}
.info-item{{background:rgba(100,80,255,0.02);border:1px solid rgba(100,80,255,0.02);border-radius:6px;padding:6px 10px;display:flex;justify-content:space-between;align-items:center;transition:.3s}}
.info-item:hover{{background:rgba(100,80,255,0.04)}}
.info-label{{font-size:9px;color:#8888BB;display:flex;align-items:center;gap:3px}}
.info-label i{{font-size:10px;color:#7C6BFF}}
.info-value{{font-size:11px;font-weight:700;color:#F0EEFF}}
.info-value.used{{color:#A78BFA}}
.info-value.proto{{font-size:8px;background:rgba(100,80,255,0.05);padding:1px 6px;border-radius:4px;border:1px solid rgba(100,80,255,0.04);}}
.progress{{margin:8px 0 10px}}
.progress-bar{{height:3px;border-radius:3px;background:rgba(100,80,255,0.04);overflow:hidden}}
.progress-fill{{height:100%;border-radius:3px;background:linear-gradient(90deg,#7C6BFF,#5B4BD9,#A78BFA);width:{percent:.1f}%;transition:width 1s ease}}
.progress-text{{display:flex;justify-content:space-between;font-size:8px;color:#8888BB;margin-top:2px}}
.progress-text .pct{{font-weight:700;color:#F0EEFF}}
.vless-section{{background:rgba(100,80,255,0.02);border:1px solid rgba(100,80,255,0.03);border-radius:8px;padding:8px 10px;margin:8px 0}}
.vless-label{{font-size:7px;color:#8888BB;font-weight:700;text-transform:uppercase;letter-spacing:.04em;display:flex;align-items:center;gap:4px;margin-bottom:4px}}
.vless-label i{{color:#7C6BFF;font-size:10px}}
.vless-link{{font-family:monospace;font-size:8px;color:#A78BFA;word-break:break-all;line-height:1.5;background:rgba(0,0,0,0.2);padding:4px 6px;border-radius:4px;border:1px solid rgba(100,80,255,0.02);}}
.actions{{display:flex;gap:4px;margin-top:8px;flex-wrap:wrap}}
.btn{{font-family:inherit;font-size:9px;font-weight:600;border-radius:6px;padding:5px 10px;cursor:pointer;display:inline-flex;align-items:center;gap:3px;border:none;transition:all .3s;white-space:nowrap;flex:1;justify-content:center}}
.btn i{{font-size:11px}}
.btn-primary{{background:linear-gradient(135deg,#7C6BFF,#5B4BD9);color:#fff;box-shadow:0 3px 15px rgba(100,80,255,0.15)}}
.btn-primary:hover{{transform:translateY(-2px);box-shadow:0 6px 25px rgba(100,80,255,0.25)}}
.btn-secondary{{background:rgba(100,80,255,0.03);border:1px solid rgba(100,80,255,0.04);color:#8888BB}}
.btn-secondary:hover{{background:rgba(100,80,255,0.06);color:#F0EEFF;transform:translateY(-2px)}}
.btn-success{{background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.08);color:#34D399}}
.btn-success:hover{{background:rgba(16,185,129,0.1);transform:translateY(-2px)}}
.footer{{margin-top:12px;padding-top:10px;border-top:1px solid rgba(100,80,255,0.02);text-align:center;font-size:7px;color:#555577}}
.footer .eagle{{color:#7C6BFF;font-weight:700}}
.toast{{position:fixed;bottom:16px;left:50%;transform:translateX(-50%) translateY(40px);background:rgba(10,10,30,0.9);backdrop-filter:blur(20px);border:1px solid rgba(100,80,255,0.08);color:#F0EEFF;border-radius:8px;padding:6px 14px;font-size:10px;opacity:0;transition:all .4s;z-index:999;pointer-events:none;display:flex;align-items:center;gap:4px;box-shadow:0 8px 30px rgba(0,0,0,0.3)}}
.toast.show{{opacity:1;transform:translateX(-50%) translateY(0)}}
.toast.ok{{border-color:rgba(16,185,129,0.15);color:#34D399}}
@media(max-width:400px){{.card{{padding:16px 14px 14px}}.user-name{{font-size:15px}}.brand-icon{{width:30px;height:30px;font-size:14px}}.info-item{{padding:4px 8px}}.btn{{font-size:8px;padding:4px 8px}}}}
</style>
</head>
<body>
<div class="stars-sub">
    <div class="star-sub" style="width:2px;height:2px;top:10%;left:10%;animation-delay:0s"></div>
    <div class="star-sub" style="width:3px;height:3px;top:30%;left:40%;animation-delay:1.5s"></div>
    <div class="star-sub" style="width:1px;height:1px;top:50%;left:70%;animation-delay:0.8s"></div>
    <div class="star-sub" style="width:2px;height:2px;top:70%;left:20%;animation-delay:2.2s"></div>
    <div class="star-sub" style="width:3px;height:3px;top:85%;left:80%;animation-delay:0.5s"></div>
</div>
<div class="glow-sub glow-sub1"></div><div class="glow-sub glow-sub2"></div>
<div class="toast" id="toast"></div>
<div class="card">
    <div class="brand"><div class="brand-icon">🪐</div><div class="brand-text"><div class="name">پنل عقاب</div><div class="sub">اطلاعات اشتراک</div></div></div>
    <div class="user-header"><div class="user-name"><span class="fire">🪐</span> {label}</div><span class="status {'active' if is_allowed else 'inactive'}"><i class="ti {'ti-circle-check' if is_allowed else 'ti-circle-x'}"></i>{'فعال' if is_allowed else 'غیرفعال'}</span></div>
    <div class="uuid-box" onclick="copyUUID()">🔑 {uuid}</div>
    {conns_html}
    <div class="info-grid">
        <div class="info-item"><span class="info-label"><i class="ti ti-database"></i> مصرف</span><span class="info-value used">{used_fmt}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-package"></i> سهمیه</span><span class="info-value">{limit_fmt}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-calendar"></i> باقیمانده</span><span class="info-value">{days_left}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-devices"></i> دستگاه</span><span class="info-value">{max_devices if max_devices > 0 else '∞'}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-clock"></i> آخرین اتصال</span><span class="info-value" style="font-size:9px;">{last_connected_text}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-ip"></i> IP</span><span class="info-value proto">{user_ip}</span></div>
        {clean_ip_html}
        <div class="info-item"><span class="info-label"><i class="ti ti-fingerprint"></i> FP</span><span class="info-value proto">{fingerprint}</span></div>
    </div>
    <div class="progress"><div class="progress-bar"><div class="progress-fill" style="width:{percent:.1f}%"></div></div><div class="progress-text"><span>میزان مصرف</span><span class="pct">{percent:.1f}%</span></div></div>
    <div class="vless-section"><div class="vless-label"><i class="ti ti-link"></i> لینک کانفیگ</div><div class="vless-link" id="vless-link">{vless_link}</div></div>
    <div class="actions"><button class="btn btn-primary" onclick="copyVless()"><i class="ti ti-copy"></i> کپی</button><button class="btn btn-success" onclick="copySub()"><i class="ti ti-link"></i> ساب</button><button class="btn btn-secondary" onclick="showQR()"><i class="ti ti-qrcode"></i> QR</button></div>
    <div class="footer"><span class="eagle">🪐</span> پنل عقاب</div>
</div>
<script>
const vless=`{vless_link}`;const subUrl=`{sub_url}`;const uuid=`{uuid}`;
function toast(msg,type=''){{const t=document.getElementById('toast');t.textContent=msg;t.className='toast show'+(type?' '+type:'');setTimeout(()=>t.classList.remove('show'),2000);}}
function copyVless(){{navigator.clipboard.writeText(vless).then(()=>toast('✅ کپی شد','ok'));}}
function copySub(){{navigator.clipboard.writeText(subUrl).then(()=>toast('✅ کپی شد','ok'));}}
function copyUUID(){{navigator.clipboard.writeText(uuid).then(()=>toast('✅ کپی شد','ok'));}}
function showQR(){{window.open('https://api.qrserver.com/v1/create-qr-code/?size=250x250&data='+encodeURIComponent(vless),'_blank');}}
</script>
</body></html>"""
