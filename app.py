from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect
import requests
import hmac
import hashlib
import time
import json
import random
import math
import re

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///dispatcher.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

OLD_APP_URL = "http://139.180.209.124"
INTERNAL_SECRET_TOKEN = "DayLaMatKhauBaoMatGiuaHaiApp123!@#"

ACTIVE_ORDERS_REGISTRY = {}

class SystemConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    core_group_name = db.Column(db.String(100), nullable=True)
    proxy_ip = db.Column(db.String(50), nullable=True)
    proxy_port = db.Column(db.String(10), nullable=True)
    proxy_user = db.Column(db.String(50), nullable=True)
    proxy_pass = db.Column(db.String(50), nullable=True)

class AccountRole(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    role = db.Column(db.String(50), default='none')

class AdConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_name = db.Column(db.String(100), nullable=False)
    fiat = db.Column(db.String(20), nullable=False)
    min_usdt = db.Column(db.String(50))
    max_usdt = db.Column(db.String(50))
    quantity = db.Column(db.String(50))
    payment_ids = db.Column(db.String(200)) 
    payment_period = db.Column(db.String(20))
    remark = db.Column(db.Text)
    trading_prefs = db.Column(db.Text)

class OrderAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(100), unique=True, nullable=False)
    assigned_group = db.Column(db.String(100), nullable=True)

class LinkedSellAd(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(100), unique=True, nullable=False)
    ad_id = db.Column(db.String(100), nullable=False)
    account_email = db.Column(db.String(150), nullable=False)

class ConfirmedOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(100), unique=True, nullable=False)

class LinkedSellOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buy_order_id = db.Column(db.String(100), nullable=False)
    sell_order_id = db.Column(db.String(100), unique=True, nullable=False)
    account_email = db.Column(db.String(150), nullable=False)

class SavedOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(100), unique=True, nullable=False)
    account_email = db.Column(db.String(150))
    group_name = db.Column(db.String(100))
    order_data = db.Column(db.Text) 
    status = db.Column(db.String(50), default='1')
    updated_at = db.Column(db.Float, default=time.time)

with app.app_context():
    db.create_all()
    try:
        inspector = inspect(db.engine)
        if 'system_config' in inspector.get_table_names():
            existing_cols_sys = [col['name'] for col in inspector.get_columns('system_config')]
            with db.engine.connect() as conn:
                if 'proxy_ip' not in existing_cols_sys: conn.execute(text("ALTER TABLE system_config ADD COLUMN proxy_ip VARCHAR(50)"))
                if 'proxy_port' not in existing_cols_sys: conn.execute(text("ALTER TABLE system_config ADD COLUMN proxy_port VARCHAR(10)"))
                if 'proxy_user' not in existing_cols_sys: conn.execute(text("ALTER TABLE system_config ADD COLUMN proxy_user VARCHAR(50)"))
                if 'proxy_pass' not in existing_cols_sys: conn.execute(text("ALTER TABLE system_config ADD COLUMN proxy_pass VARCHAR(50)"))
                conn.commit()
                
        if 'ad_config' in inspector.get_table_names():
            existing_cols_ad = [col['name'] for col in inspector.get_columns('ad_config')]
            with db.engine.connect() as conn:
                if 'min_usdt' not in existing_cols_ad: conn.execute(text("ALTER TABLE ad_config ADD COLUMN min_usdt VARCHAR(50)"))
                if 'max_usdt' not in existing_cols_ad: conn.execute(text("ALTER TABLE ad_config ADD COLUMN max_usdt VARCHAR(50)"))
                conn.commit()
    except Exception as e: pass

    if not SystemConfig.query.first():
        db.session.add(SystemConfig(core_group_name=""))
        db.session.commit()

@app.route('/')
def index():
    config = SystemConfig.query.first()
    return render_template('index.html', core_group=config.core_group_name)

@app.route('/api/get_groups', methods=['GET'])
def get_groups():
    try:
        res = requests.get(f"{OLD_APP_URL}/api/get_bb_sp_groups", timeout=10)
        if res.status_code == 200: return jsonify(res.json())
        return jsonify({"status": "error", "message": "App cũ trả về lỗi HTTP"}), 500
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_accounts', methods=['GET'])
def get_accounts():
    group_name = request.args.get('group')
    if not group_name: return jsonify({"status": "error", "message": "Thiếu tên nhóm"}), 400
    try:
        headers = { 'X-Internal-Token': INTERNAL_SECRET_TOKEN }
        res = requests.get(f"{OLD_APP_URL}/api/internal/get_keys?group={group_name}", headers=headers, timeout=10)
        if res.status_code == 200:
            accounts = res.json().get('accounts', [])
            accounts_data = []
            for acc in accounts:
                email = acc.get('email')
                api_key = acc.get('api_key', '')
                masked_api = f"{api_key[:5]}***{api_key[-5:]}" if api_key and len(api_key) >= 10 else ("***" if api_key else "")
                record = AccountRole.query.filter_by(email=email).first()
                accounts_data.append({"email": email, "masked_api": masked_api, "role": record.role if record else 'none'})
            return jsonify({"status": "success", "accounts": accounts_data})
        return jsonify({"status": "error", "message": "App cũ trả về lỗi HTTP"}), 500
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_config', methods=['POST'])
def save_config():
    data = request.json
    try:
        config = SystemConfig.query.first()
        config.core_group_name = data.get('core_group')
        for acc in data.get('accounts', []):
            record = AccountRole.query.filter_by(email=acc['email']).first()
            if not record: db.session.add(AccountRole(email=acc['email'], role=acc['role']))
            else: record.role = acc['role']
        db.session.commit()
        return jsonify({"status": "success", "message": "Đã lưu cấu hình thành công!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_proxy', methods=['GET'])
def get_proxy():
    config = SystemConfig.query.first()
    return jsonify({"status": "success", "proxy": {"ip": config.proxy_ip or "", "port": config.proxy_port or "", "user": config.proxy_user or "", "pass": config.proxy_pass or ""}})

@app.route('/api/save_proxy', methods=['POST'])
def save_proxy():
    try:
        config = SystemConfig.query.first()
        config.proxy_ip = request.json.get('ip')
        config.proxy_port = request.json.get('port')
        config.proxy_user = request.json.get('user')
        config.proxy_pass = request.json.get('pass')
        db.session.commit()
        return jsonify({"status": "success", "message": "Đã lưu Proxy!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

def get_bybit_headers(api_key, api_secret, payload_str="{}"):
    ts = str(int(time.time() * 1000))
    sig = hmac.new(bytes(api_secret, "utf-8"), (ts + api_key + "5000" + payload_str).encode("utf-8"), hashlib.sha256).hexdigest()
    return {'X-BAPI-API-KEY': api_key, 'X-BAPI-SIGN': sig, 'X-BAPI-TIMESTAMP': ts, 'X-BAPI-RECV-WINDOW': "5000", 'Content-Type': 'application/json'}

def _normalize_payment_name(name):
    compact = re.sub(r'[^A-Z0-9]+', ' ', str(name or '').upper()).strip()
    return re.sub(r'\s+', ' ', compact)

def _normalize_payment_names(raw_payments):
    if raw_payments is None:
        return []
    if isinstance(raw_payments, str):
        candidates = [p.strip() for p in raw_payments.split(',') if p and p.strip()]
    elif isinstance(raw_payments, (list, tuple, set)):
        candidates = []
        for p in raw_payments:
            if isinstance(p, dict):
                name = p.get("paymentName") or p.get("name") or p.get("payment_name")
                if name:
                    candidates.append(str(name).strip())
            elif p is not None:
                candidates.append(str(p).strip())
    else:
        candidates = [str(raw_payments).strip()]
    return [_normalize_payment_name(p) for p in candidates if p]

def _extract_payments_from_obj(data_obj):
    if not isinstance(data_obj, dict):
        return []
    for key in ("payments", "payment_methods", "paymentMethods", "pttt_str"):
        if key in data_obj and data_obj.get(key) not in (None, "", []):
            return _normalize_payment_names(data_obj.get(key))
    return []

def _payments_overlap(requested_payments, candidate_payments):
    if not requested_payments:
        return True
    if not candidate_payments:
        return False
    for req in requested_payments:
        for cand in candidate_payments:
            if req == cand or cand.startswith(f"{req} ") or req.startswith(f"{cand} "):
                return True
    return False

def _find_price_entry(prices_data, fiat, requested_payments):
    fiat_upper = (fiat or "").upper()
    normalized_requested = _normalize_payment_names(requested_payments)
    first_currency_match = None
    for price in prices_data:
        if (price.get('currency', '') or '').upper() != fiat_upper:
            continue
        if first_currency_match is None:
            first_currency_match = price
        if _payments_overlap(normalized_requested, _extract_payments_from_obj(price)):
            return price
    if normalized_requested:
        return None
    return first_currency_match

@app.route('/api/get_buy_ads_dashboard', methods=['GET'])
def get_buy_ads_dashboard():
    group_name = request.args.get('group')
    if not group_name: return jsonify({"status": "error", "message": "Thiếu nhóm"}), 400
    try:
        configs, raw_ads, raw_pending_orders = [], [], []
        assignments = {a.order_id: a.assigned_group for a in OrderAssignment.query.all()}
        confirmed_db = ConfirmedOrder.query.all()
        confirmed_orders_dict = {str(c.order_id): True for c in confirmed_db}

        prices_data = []
        try:
            res_prices = requests.get(f"{OLD_APP_URL}/api/prices", timeout=10)
            if res_prices.status_code == 200:
                prices_data = res_prices.json().get('data', [])
        except: pass

        try:
            res1 = requests.get(f"{OLD_APP_URL}/api/get_market_config", timeout=10)
            if res1.status_code == 200: 
                configs = res1.json().get('data', [])
                for c in configs: 
                    fiat = c.get('fiat', '')
                    matched_price = _find_price_entry(prices_data, fiat, _extract_payments_from_obj(c))
                    c['ref_price'] = matched_price.get('buy_price_raw', 0) if matched_price else 0
                    c['ref_price_str'] = matched_price.get('buy_price', 'N/A') if matched_price else 'N/A'
        except: pass
        
        buy_accounts = [acc.email for acc in AccountRole.query.filter_by(role='buy').all()]
        sell_accounts = [acc.email for acc in AccountRole.query.filter_by(role='sell').all()]
        
        try:
            res2 = requests.get(f"{OLD_APP_URL}/api/fetch_group_ads?group={group_name}", timeout=20)
            if res2.status_code == 200: raw_ads = res2.json().get('ads', [])
        except: pass
        try:
            res3 = requests.get(f"{OLD_APP_URL}/api/get_pending_orders?group={group_name}", timeout=10)
            if res3.status_code == 200: raw_pending_orders = res3.json().get('data', {}).get('items', [])
        except: pass

        sys_cfg = SystemConfig.query.first()
        proxies = None
        if sys_cfg and sys_cfg.proxy_ip and sys_cfg.proxy_port:
            p_url = f"http://{sys_cfg.proxy_user}:{sys_cfg.proxy_pass}@{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}" if sys_cfg.proxy_user else f"http://{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}"
            proxies = {"http": p_url, "https": p_url}

        headers_int = { 'X-Internal-Token': INTERNAL_SECRET_TOKEN }
        res_keys = requests.get(f"{OLD_APP_URL}/api/internal/get_keys?group={group_name}", headers=headers_int, timeout=10)
        all_accs = res_keys.json().get('accounts', []) if res_keys.status_code == 200 else []

        # ==========================================
        # LOGIC LƯU TRỮ VÀ CẬP NHẬT TRẠNG THÁI ĐƠN
        # ==========================================
        current_time = time.time()
        active_ids = []
        for po in raw_pending_orders:
            po_id = str(po['id'])
            active_ids.append(po_id)
            record = SavedOrder.query.filter_by(order_id=po_id).first()
            if not record:
                record = SavedOrder(order_id=po_id, account_email=po.get('account_name'), group_name=group_name)
                db.session.add(record)
            
            old_status = record.status
            new_status = str(po.get('status', '1'))
            record.order_data = json.dumps(po)
            record.status = new_status
            if old_status != new_status:
                record.updated_at = current_time # Chỉ cập nhật thời gian khi status thay đổi
        db.session.commit()

        # Kiểm tra các đơn trong DB có trạng thái đang chờ xử lý nhưng app cũ không trả về nữa
        missing_orders = SavedOrder.query.filter_by(group_name=group_name).all()
        for mo in missing_orders:
            # 1: New, 2: Pending (Bybit status thường là 1, 2, 10, 20 là đang chờ)
            if mo.order_id not in active_ids and mo.status in ['1', '2', '10', '20', 'New', 'Pending', 'InProgress']:
                acc = next((a for a in all_accs if a.get('email') == mo.account_email), None)
                if acc and acc.get('api_key'):
                    try:
                        payload_str = json.dumps({"orderId": mo.order_id})
                        req_headers = get_bybit_headers(acc['api_key'], acc['api_secret'], payload_str)
                        res_info = requests.post("https://api.bybit.com/v5/p2p/order/info", headers=req_headers, data=payload_str, proxies=proxies, timeout=5).json()
                        if str(res_info.get("retCode", res_info.get("ret_code"))) == "0":
                            result_data = res_info.get("result", {})
                            real_status = str(result_data.get("status", mo.status))
                            
                            # Nếu Bybit trả về trạng thái mới (Hoàn thành / Hủy) thì chốt thời gian
                            if mo.status != real_status:
                                mo.status = real_status
                                mo.updated_at = current_time
                            
                            old_data = json.loads(mo.order_data) if mo.order_data else {}
                            old_data.update(result_data)
                            mo.order_data = json.dumps(old_data)
                    except: pass
        db.session.commit()

        # Đóng gói toàn bộ đơn đã lưu để gửi xuống Frontend hiển thị
        all_db_orders = SavedOrder.query.filter_by(group_name=group_name).all()
        db_orders_parsed = []
        for d_ord in all_db_orders:
            parsed = json.loads(d_ord.order_data) if d_ord.order_data else {}
            parsed['db_status'] = d_ord.status
            parsed['updated_at'] = d_ord.updated_at
            db_orders_parsed.append(parsed)
        # ==========================================

        buy_ads = [ad for ad in raw_ads if ad.get('account_email') in buy_accounts and str(ad.get('side')) == '0']
        pending_orders = [po for po in raw_pending_orders if po.get('account_name') in buy_accounts and str(po.get('side')) == '0']
        sell_pending_orders = [po for po in raw_pending_orders if po.get('account_name') in sell_accounts and str(po.get('side')) == '1']

        for spo in sell_pending_orders:
            spo_id = str(spo['id'])
            acc_email = spo.get('account_name')
            db_record = LinkedSellOrder.query.filter_by(sell_order_id=spo_id).first()
            if not db_record:
                acc = next((a for a in all_accs if a.get('email') == acc_email), None)
                if acc and acc.get('api_key'):
                    try:
                        payload_str = json.dumps({"orderId": spo_id})
                        req_headers = get_bybit_headers(acc['api_key'], acc['api_secret'], payload_str)
                        res_info = requests.post("https://api.bybit.com/v5/p2p/order/info", headers=req_headers, data=payload_str, proxies=proxies, timeout=5).json()
                        if str(res_info.get("retCode", res_info.get("ret_code"))) == "0":
                            item_id = str(res_info.get("result", {}).get("itemId", ""))
                            linked_ad = LinkedSellAd.query.filter_by(ad_id=item_id).first()
                            if linked_ad:
                                new_link = LinkedSellOrder(buy_order_id=linked_ad.order_id, sell_order_id=spo_id, account_email=acc_email)
                                db.session.add(new_link)
                                db.session.commit()
                    except: pass

        linked_sell_orders_data = {}
        all_sell_links = LinkedSellOrder.query.all()
        for link in all_sell_links:
            matched_spo = next((spo for spo in sell_pending_orders if str(spo['id']) == link.sell_order_id), None)
            if matched_spo:
                if link.buy_order_id not in linked_sell_orders_data:
                    linked_sell_orders_data[link.buy_order_id] = []
                linked_sell_orders_data[link.buy_order_id].append(matched_spo)

        linked_ads_db = LinkedSellAd.query.all()
        linked_ads_data = {}
        for link in linked_ads_db:
            acc = next((a for a in all_accs if a.get('email') == link.account_email), None)
            if acc and acc.get('api_key'):
                try:
                    payload_str = json.dumps({"itemId": str(link.ad_id)})
                    req_headers = get_bybit_headers(acc['api_key'], acc['api_secret'], payload_str)
                    res_p = requests.post("https://api.bybit.com/v5/p2p/item/personal/list", headers=req_headers, data=payload_str, proxies=proxies, timeout=5).json()
                    if str(res_p.get("retCode", res_p.get("ret_code"))) == "0":
                        items = res_p.get("result", {}).get("items", [])
                        if items:
                            ad_info = items[0]
                            ad_info['account_email'] = link.account_email 
                            linked_ads_data[link.order_id] = ad_info
                except: pass
        
        return jsonify({
            "status": "success", 
            "configs": configs, 
            "all_ads": raw_ads,
            "all_pending_orders": raw_pending_orders,
            "buy_ads": buy_ads, 
            "pending_orders": pending_orders, 
            "assignments": assignments,
            "confirmed_orders": confirmed_orders_dict,
            "linked_sell_ads": linked_ads_data,
            "linked_sell_orders": linked_sell_orders_data,
            "saved_orders_history": db_orders_parsed  # <-- BIẾN NÀY ĐƯỢC THÊM VÀO ĐỂ FRONTEND DÙNG
        })
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_ad_config', methods=['GET'])
def get_ad_config():
    group, fiat = request.args.get('group'), request.args.get('fiat')
    record = AdConfig.query.filter_by(group_name=group, fiat=fiat).first()
    if record:
        return jsonify({"status": "success", "data": {"minUsdt": record.min_usdt, "maxUsdt": record.max_usdt, "quantity": record.quantity, "remark": record.remark, "tradingPreferenceSet": json.loads(record.trading_prefs) if record.trading_prefs else {}}})
    return jsonify({"status": "empty", "data": {}})

@app.route('/api/save_ad_config', methods=['POST'])
def save_ad_config():
    data = request.json
    try:
        record = AdConfig.query.filter_by(group_name=data.get('group'), fiat=data.get('fiat')).first()
        if not record:
            record = AdConfig(group_name=data.get('group'), fiat=data.get('fiat'))
            db.session.add(record)
        record.min_usdt = data.get('minUsdt')
        record.max_usdt = data.get('maxUsdt')
        record.quantity = data.get('quantity')
        record.payment_period = '30'
        record.remark = data.get('remark')
        record.trading_prefs = json.dumps(data.get('tradingPreferenceSet', {}))
        db.session.commit()
        return jsonify({"status": "success", "message": "Đã lưu cấu hình Quảng cáo!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_ad_info', methods=['POST'])
def get_ad_info():
    data = request.json
    group, email, item_id = data.get('group'), data.get('email'), data.get('item_id')
    if not group or not email or not item_id: return jsonify({"status": "error", "message": "Thiếu thông tin gửi lên"}), 400
    try:
        headers = { 'X-Internal-Token': INTERNAL_SECRET_TOKEN }
        res = requests.get(f"{OLD_APP_URL}/api/internal/get_keys?group={group}", headers=headers, timeout=10)
        if res.status_code != 200: return jsonify({"status": "error", "message": "Lỗi lấy Key từ App Cũ"}), 500
        all_accounts = res.json().get('accounts', [])
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

    target_acc = next((a for a in all_accounts if a.get('email') == email), None)
    if not target_acc or not target_acc.get('api_key') or not target_acc.get('api_secret'): return jsonify({"status": "error", "message": "Tài khoản không có API Key hợp lệ!"}), 400

    sys_cfg = SystemConfig.query.first()
    proxies = None
    if sys_cfg and sys_cfg.proxy_ip and sys_cfg.proxy_port:
        p_url = f"http://{sys_cfg.proxy_user}:{sys_cfg.proxy_pass}@{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}" if sys_cfg.proxy_user else f"http://{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}"
        proxies = {"http": p_url, "https": p_url}

    try:
        payload_str = json.dumps({"itemId": str(item_id)})
        req_headers = get_bybit_headers(target_acc['api_key'], target_acc['api_secret'], payload_str)
        res_bybit = requests.post("https://api.bybit.com/v5/p2p/item/info", headers=req_headers, data=payload_str, proxies=proxies, timeout=15).json()
        
        if str(res_bybit.get("retCode", res_bybit.get("ret_code"))) == "0": return jsonify({"status": "success", "data": res_bybit.get("result", {})})
        else: return jsonify({"status": "error", "message": f"Bybit báo lỗi: {res_bybit.get('retMsg', res_bybit.get('ret_msg'))}"})
    except Exception as e: return jsonify({"status": "error", "message": f"Lỗi gọi Bybit: {str(e)}"}), 500

@app.route('/api/get_order_info', methods=['POST'])
def get_order_info():
    data = request.json
    group, email, order_id = data.get('group'), data.get('email'), data.get('order_id')
    if not group or not email or not order_id: return jsonify({"status": "error", "message": "Thiếu thông tin gửi lên"}), 400

    try:
        headers = { 'X-Internal-Token': INTERNAL_SECRET_TOKEN }
        res = requests.get(f"{OLD_APP_URL}/api/internal/get_keys?group={group}", headers=headers, timeout=10)
        if res.status_code != 200: return jsonify({"status": "error", "message": "Lỗi lấy Key từ App Cũ"}), 500
        all_accounts = res.json().get('accounts', [])
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

    target_acc = next((a for a in all_accounts if a.get('email') == email), None)
    if not target_acc or not target_acc.get('api_key') or not target_acc.get('api_secret'): return jsonify({"status": "error", "message": "Tài khoản không có API Key hợp lệ!"}), 400

    sys_cfg = SystemConfig.query.first()
    proxies = None
    if sys_cfg and sys_cfg.proxy_ip and sys_cfg.proxy_port:
        p_url = f"http://{sys_cfg.proxy_user}:{sys_cfg.proxy_pass}@{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}" if sys_cfg.proxy_user else f"http://{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}"
        proxies = {"http": p_url, "https": p_url}

    try:
        payload_str = json.dumps({"orderId": str(order_id)})
        req_headers = get_bybit_headers(target_acc['api_key'], target_acc['api_secret'], payload_str)
        res_bybit = requests.post("https://api.bybit.com/v5/p2p/order/info", headers=req_headers, data=payload_str, proxies=proxies, timeout=15).json()
        
        if str(res_bybit.get("retCode", res_bybit.get("ret_code"))) == "0": return jsonify({"status": "success", "data": res_bybit.get("result", {})})
        else: return jsonify({"status": "error", "message": f"Bybit báo lỗi: {res_bybit.get('retMsg', res_bybit.get('ret_msg'))}"})
    except Exception as e: return jsonify({"status": "error", "message": f"Lỗi gọi Bybit: {str(e)}"}), 500

@app.route('/api/cancel_ad', methods=['POST'])
def cancel_ad():
    data = request.json
    group, email, item_id = data.get('group'), data.get('email'), data.get('item_id')
    logs = []
    if not group or not email or not item_id: return jsonify({"status": "error", "message": "Thiếu thông tin", "logs": logs}), 400
    logs.append(f"Yêu cầu xóa QC ID {item_id} trên tài khoản {email}...")

    try:
        headers = { 'X-Internal-Token': INTERNAL_SECRET_TOKEN }
        res = requests.get(f"{OLD_APP_URL}/api/internal/get_keys?group={group}", headers=headers, timeout=10)
        if res.status_code != 200: return jsonify({"status": "error", "message": "Lỗi lấy Key", "logs": logs}), 500
        all_accounts = res.json().get('accounts', [])
    except Exception as e: return jsonify({"status": "error", "message": str(e), "logs": logs}), 500

    target_acc = next((a for a in all_accounts if a.get('email') == email), None)
    if not target_acc or not target_acc.get('api_key'): return jsonify({"status": "error", "message": "API Key ko hợp lệ", "logs": logs}), 400

    sys_cfg = SystemConfig.query.first()
    proxies = None
    if sys_cfg and sys_cfg.proxy_ip and sys_cfg.proxy_port:
        p_url = f"http://{sys_cfg.proxy_user}:{sys_cfg.proxy_pass}@{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}" if sys_cfg.proxy_user else f"http://{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}"
        proxies = {"http": p_url, "https": p_url}

    try:
        payload_str = json.dumps({"itemId": str(item_id)})
        req_headers = get_bybit_headers(target_acc['api_key'], target_acc['api_secret'], payload_str)
        logs.append(f"Đang gửi lệnh Xóa...")
        res_bybit = requests.post("https://api.bybit.com/v5/p2p/item/cancel", headers=req_headers, data=payload_str, proxies=proxies, timeout=15).json()
        
        if str(res_bybit.get("retCode", res_bybit.get("ret_code"))) == "0":
            LinkedSellAd.query.filter_by(ad_id=str(item_id)).delete()
            db.session.commit()
            logs.append(f"Thành công: Đã xóa hoàn toàn QC {item_id}.")
            return jsonify({"status": "success", "message": "Đã xóa", "logs": logs})
        else:
            err_msg = res_bybit.get('retMsg') or res_bybit.get('ret_msg') or json.dumps(res_bybit)
            logs.append(f"Thất bại: {err_msg}")
            return jsonify({"status": "error", "message": err_msg, "logs": logs})
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return jsonify({"status": "error", "message": str(e), "logs": logs}), 500

@app.route('/api/auto_create_ad', methods=['POST'])
def auto_create_ad():
    data = request.json
    group, fiat, pttt_str = data.get('group'), data.get('fiat'), data.get('pttt_str', '')
    logs = []
    ad_cfg = AdConfig.query.filter_by(group_name=group, fiat=fiat).first()
    if not ad_cfg: return jsonify({"status": "error", "message": f"Chưa có Cấu hình QC cho {fiat}.", "logs": logs}), 400

    min_usdt, max_usdt, qty = float(ad_cfg.min_usdt or 0), float(ad_cfg.max_usdt or 0), float(ad_cfg.quantity or 0)
    if min_usdt <= 0 or max_usdt <= 0 or qty <= 0: return jsonify({"status": "error", "message": "Min/Max/Qty = 0.", "logs": logs}), 400

    buy_emails = [r.email for r in AccountRole.query.filter_by(role='buy').all()]
    if not buy_emails: return jsonify({"status": "error", "message": "Ko có ACC MUA!", "logs": logs}), 400

    allowed_payment_names = [p.strip().upper() for p in pttt_str.split(',') if p.strip()]
    
    try:
        res_prices = requests.get(f"{OLD_APP_URL}/api/prices", timeout=10)
        prices_data = res_prices.json().get('data', [])
        matched_price = _find_price_entry(prices_data, fiat, pttt_str)
        matched_price_data = matched_price or {}
        buy_price_str = str(matched_price_data.get('buy_price', '0')).replace(',', '')
        buy_price_raw = float(matched_price_data.get('buy_price_raw', 0) or 0)
    except: 
        buy_price_str = "0"
        buy_price_raw = 0

    if buy_price_raw <= 0: return jsonify({"status": "error", "message": "Ko kéo được giá!", "logs": logs}), 400
    
    fiat_min, fiat_max = min_usdt * buy_price_raw, max_usdt * buy_price_raw

    try:
        headers = { 'X-Internal-Token': INTERNAL_SECRET_TOKEN }
        res = requests.get(f"{OLD_APP_URL}/api/internal/get_keys?group={group}", headers=headers, timeout=10)
        all_accounts = res.json().get('accounts', []) if res.status_code == 200 else []
    except Exception as e: return jsonify({"status": "error", "message": str(e), "logs": logs}), 500

    valid_accs = [a for a in all_accounts if a.get('email') in buy_emails and a.get('api_key')]
    random.shuffle(valid_accs)
    
    sys_cfg = SystemConfig.query.first()
    proxies = None
    if sys_cfg and sys_cfg.proxy_ip and sys_cfg.proxy_port:
        p_url = f"http://{sys_cfg.proxy_user}:{sys_cfg.proxy_pass}@{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}" if sys_cfg.proxy_user else f"http://{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}"
        proxies = {"http": p_url, "https": p_url}

    is_success = False
    success_msg = ""

    for acc in valid_accs:
        acc_email = acc['email']
        try:
            pay_headers = get_bybit_headers(acc['api_key'], acc['api_secret'], "{}")
            res_pay = requests.post("https://api.bybit.com/v5/p2p/user/payment/list", headers=pay_headers, data="{}", proxies=proxies, timeout=15).json()
            if str(res_pay.get("retCode", res_pay.get("ret_code"))) != "0": 
                err = res_pay.get("retMsg") or res_pay.get("ret_msg") or json.dumps(res_pay)
                logs.append(f"[{acc_email}] Lỗi gọi Bybit: {err}")
                continue
                
            fetched_payments = res_pay.get("result", [])
            valid_pids = []
            payments_by_name = {}
            for p in fetched_payments:
                if str(p.get("id")) == "-1": continue
                p_name = p.get("paymentConfigVo", {}).get("paymentName", "").strip().upper()
                if p_name in allowed_payment_names:
                    if p_name not in payments_by_name:
                        payments_by_name[p_name] = []
                    payments_by_name[p_name].append(str(p["id"]))
            
            for p_name, ids in payments_by_name.items():
                valid_pids.append(random.choice(ids))
                
            if not valid_pids: 
                logs.append(f"[{acc_email}] Nick CHƯA ADD các PTTT ({pttt_str})")
                continue

            raw_prefs = json.loads(ad_cfg.trading_prefs) if ad_cfg and ad_cfg.trading_prefs else {}
            bybit_prefs = {}
            bool_keys = ["hasUnPostAd", "isKyc", "isEmail", "isMobile", "hasRegisterTime", "hasOrderFinishNumberDay30", "hasCompleteRateDay30", "hasNationalLimit"]
            
            for k, v in raw_prefs.items():
                if k in bool_keys:
                    if str(v).lower() in ['true', '1', 'yes']: bybit_prefs[k] = "1"
                    else: bybit_prefs[k] = "0"
                else: bybit_prefs[k] = str(v)

            payload = {
                "tokenId": "USDT", "currencyId": fiat.upper(), "side": "0", "priceType": "0", "premium": "",
                "price": buy_price_str, 
                "minAmount": "{:.2f}".format(fiat_min).rstrip('0').rstrip('.'), 
                "maxAmount": "{:.2f}".format(fiat_max).rstrip('0').rstrip('.'),
                "quantity": str(qty), "paymentPeriod": "30", "itemType": "ORIGIN", 
                "paymentIds": valid_pids[:5], 
                "remark": ad_cfg.remark or "", "tradingPreferenceSet": bybit_prefs
            }

            payload_str = json.dumps(payload)
            req_headers = get_bybit_headers(acc['api_key'], acc['api_secret'], payload_str)
            res_bybit = requests.post("https://api.bybit.com/v5/p2p/item/create", headers=req_headers, data=payload_str, proxies=proxies, timeout=15).json()
            
            if str(res_bybit.get("retCode", res_bybit.get("ret_code"))) == "0":
                success_msg = f"Thành công! Ads ID: {res_bybit.get('result', {}).get('itemId', '')} ({acc_email})"
                logs.append(success_msg)
                is_success = True
                break 
            else:
                err = res_bybit.get("retMsg") or res_bybit.get("ret_msg") or json.dumps(res_bybit)
                logs.append(f"[{acc_email}] Sàn từ chối: {err}")
        except Exception as e: 
            logs.append(f"[{acc_email}] Lỗi: {str(e)}")
            continue

    if is_success: return jsonify({"status": "success", "message": success_msg, "logs": logs})
    return jsonify({"status": "error", "message": "Tạo QC thất bại.", "logs": logs}), 400

@app.route('/api/assign_group', methods=['POST'])
def assign_group():
    data = request.json
    order_id, group_name = data.get('order_id'), data.get('group_name')
    try:
        record = OrderAssignment.query.filter_by(order_id=str(order_id)).first()
        if not record: db.session.add(OrderAssignment(order_id=str(order_id), assigned_group=group_name))
        else: record.assigned_group = group_name
        db.session.commit()
        return jsonify({"status": "success", "message": "Đã gán nhóm thành công"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/sync_front_state', methods=['POST'])
def sync_front_state():
    global ACTIVE_ORDERS_REGISTRY
    group = request.json.get('group')
    orders = request.json.get('orders', [])
    if not group: return jsonify({"status": "error", "message": "Missing group"}), 400
    
    current_ids = {str(o['id']) for o in orders}
    keys_to_delete = [oid for oid, odata in ACTIVE_ORDERS_REGISTRY.items() if odata.get('owner_group') == group and oid not in current_ids]
    for k in keys_to_delete: del ACTIVE_ORDERS_REGISTRY[k]
    for o in orders: ACTIVE_ORDERS_REGISTRY[str(o['id'])] = o
        
    return jsonify({"status": "success"})

@app.route('/api/export_orders', methods=['GET'])
def export_orders():
    try:
        assigns = {a.order_id: a.assigned_group for a in OrderAssignment.query.all()}
        confirmed_db = ConfirmedOrder.query.all()
        confirmed_orders_dict = {str(c.order_id): True for c in confirmed_db}
        export_data = []
        for oid, odata in ACTIVE_ORDERS_REGISTRY.items():
            export_data.append({
                "order_id": oid, "owner_account": odata.get('owner_account'),
                "owner_group": odata.get('owner_group'), "assigned_group": assigns.get(oid, ""),
                "status": odata.get('status'), "is_confirmed": confirmed_orders_dict.get(oid, False)
            })
        return jsonify({"status": "success", "total": len(export_data), "data": export_data})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/confirm_order', methods=['POST'])
def confirm_order():
    try:
        data = request.json
        order_id, action = str(data['order_id']), data.get('action', 'confirmed')
        if action == 'confirmed':
            if not ConfirmedOrder.query.filter_by(order_id=order_id).first():
                db.session.add(ConfirmedOrder(order_id=order_id))
                db.session.commit()
        elif action == 'unconfirmed':
            ConfirmedOrder.query.filter_by(order_id=order_id).delete()
            db.session.commit()
        return jsonify({'status': 'success', 'message': f'Đã ghi nhận trạng thái {action}'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/create_sell_ad_from_order', methods=['POST'])
def create_sell_ad_from_order():
    data = request.json
    order_id, group, email, fiat, pttt_name = data.get('order_id'), data.get('group'), data.get('account_email'), data.get('fiat'), data.get('pttt_name', '').strip().upper()
    logs = []
    logs.append(f"Yêu cầu TẠO QC BÁN cho đơn {order_id} ({fiat})...")
    
    try: fiat_amount, price = float(data.get('fiat_amount', 0)), float(data.get('price', 0))
    except: 
        logs.append("Lỗi: Sai định dạng giá hoặc số lượng.")
        return jsonify({"status": "error", "message": "Sai định dạng giá", "logs": logs}), 400

    raw_qty = fiat_amount / price
    quantity = math.ceil(raw_qty * 10000) / 10000.0
    ad_cfg = AdConfig.query.filter_by(group_name=group, fiat=fiat).first()
    sell_emails = [r.email for r in AccountRole.query.filter_by(role='sell').all()]

    try:
        headers = { 'X-Internal-Token': INTERNAL_SECRET_TOKEN }
        res = requests.get(f"{OLD_APP_URL}/api/internal/get_keys?group={group}", headers=headers, timeout=10)
        all_accounts = res.json().get('accounts', []) if res.status_code == 200 else []
    except Exception as e: 
        logs.append(f"Lỗi lấy cấu hình từ server cũ: {str(e)}")
        return jsonify({"status": "error", "message": str(e), "logs": logs}), 500

    valid_accs = [a for a in all_accounts if a.get('email') in sell_emails and a.get('api_key')]
    if not valid_accs:
        logs.append("Thất bại: Không có tài khoản nào được gán nhãn ACC BÁN hoặc thiếu API Key.")
        return jsonify({"status": "error", "message": "Các ACC BÁN không có API Key hợp lệ", "logs": logs}), 400

    random.shuffle(valid_accs)
    
    sys_cfg = SystemConfig.query.first()
    proxies = None
    if sys_cfg and sys_cfg.proxy_ip and sys_cfg.proxy_port:
        p_url = f"http://{sys_cfg.proxy_user}:{sys_cfg.proxy_pass}@{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}" if sys_cfg.proxy_user else f"http://{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}"
        proxies = {"http": p_url, "https": p_url}

    for acc in valid_accs:
        try:
            pay_headers = get_bybit_headers(acc['api_key'], acc['api_secret'], "{}")
            res_pay = requests.post("https://api.bybit.com/v5/p2p/user/payment/list", headers=pay_headers, data="{}", proxies=proxies, timeout=15).json()
            if str(res_pay.get("retCode", res_pay.get("ret_code"))) != "0": 
                err = res_pay.get("retMsg") or res_pay.get("ret_msg") or json.dumps(res_pay)
                logs.append(f"[{acc['email']}] Lỗi gọi Bybit: {err}")
                continue
                
            fetched_payments = res_pay.get("result", [])
            matched_ids = [str(p["id"]) for p in fetched_payments if str(p.get("id")) != "-1" and p.get("paymentConfigVo", {}).get("paymentName", "").strip().upper() == pttt_name]
            
            valid_pids = [random.choice(matched_ids)] if matched_ids else []
            
            if not valid_pids: 
                logs.append(f"[{acc['email']}] Bỏ qua vì nick này CHƯA ADD PTTT: {pttt_name}")
                continue 

            raw_prefs = json.loads(ad_cfg.trading_prefs) if ad_cfg and ad_cfg.trading_prefs else {}
            bybit_prefs = {}
            bool_keys = ["hasUnPostAd", "isKyc", "isEmail", "isMobile", "hasRegisterTime", "hasOrderFinishNumberDay30", "hasCompleteRateDay30", "hasNationalLimit"]
            
            for k, v in raw_prefs.items():
                if k in bool_keys:
                    if str(v).lower() in ['true', '1', 'yes']: bybit_prefs[k] = "1"
                    else: bybit_prefs[k] = "0"
                else: bybit_prefs[k] = str(v)

            payload = {
                "tokenId": "USDT", "currencyId": fiat.upper(), "side": "1", "priceType": "0", "premium": "",
                "price": "{:.4f}".format(price).rstrip('0').rstrip('.'), 
                "minAmount": "{:.2f}".format(fiat_amount).rstrip('0').rstrip('.'), 
                "maxAmount": "{:.2f}".format(fiat_amount).rstrip('0').rstrip('.'),
                "quantity": "{:.4f}".format(quantity).rstrip('0').rstrip('.'), 
                "paymentPeriod": "30", "itemType": "ORIGIN", 
                "paymentIds": [valid_pids[0]], 
                "remark": ad_cfg.remark or "" if ad_cfg else "",
                "tradingPreferenceSet": bybit_prefs
            }

            payload_str = json.dumps(payload)
            req_headers = get_bybit_headers(acc['api_key'], acc['api_secret'], payload_str)
            logs.append(f"[{acc['email']}] Đang đẩy lệnh tạo QC Bán lên sàn...")
            res_bybit = requests.post("https://api.bybit.com/v5/p2p/item/create", headers=req_headers, data=payload_str, proxies=proxies, timeout=15).json()
            
            if str(res_bybit.get("retCode", res_bybit.get("ret_code"))) == "0":
                item_id = res_bybit.get('result', {}).get('itemId', '')
                logs.append(f"Thành công! Đã tạo QC Bán ID: {item_id} trên nick {acc['email']}")
                record = LinkedSellAd.query.filter_by(order_id=str(order_id)).first()
                if not record: db.session.add(LinkedSellAd(order_id=str(order_id), ad_id=item_id, account_email=acc['email']))
                else: record.ad_id, record.account_email = item_id, acc['email']
                db.session.commit()
                return jsonify({"status": "success", "logs": logs})
            else:
                err = res_bybit.get("retMsg") or res_bybit.get("ret_msg") or json.dumps(res_bybit)
                logs.append(f"[{acc['email']}] Thất bại. Sàn từ chối: {err}")
        except Exception as e: 
            logs.append(f"[{acc['email']}] Lỗi hệ thống: {str(e)}")
            continue

    logs.append("Thất bại: Đã thử toàn bộ ACC BÁN nhưng không có nick nào phù hợp để tạo QC.")
    return jsonify({"status": "error", "message": f"Không có tài khoản BÁN đủ điều kiện.", "logs": logs}), 400

@app.route('/api/update_ad', methods=['POST'])
def update_ad():
    data = request.json
    group = data.get('group')
    email = data.get('email')
    item_id = data.get('id')
    pttt_str = data.get('pttt_str', '')  
    logs = []

    if not group or not email or not item_id: 
        return jsonify({"status": "error", "message": "Thiếu thông tin gửi lên", "logs": logs}), 400

    logs.append(f"Yêu cầu CẬP NHẬT QC ID {item_id} trên tài khoản {email}...")

    try:
        headers = { 'X-Internal-Token': INTERNAL_SECRET_TOKEN }
        res = requests.get(f"{OLD_APP_URL}/api/internal/get_keys?group={group}", headers=headers, timeout=10)
        if res.status_code != 200: 
            return jsonify({"status": "error", "message": "Lỗi lấy Key", "logs": logs}), 500
        all_accounts = res.json().get('accounts', [])
    except Exception as e: 
        return jsonify({"status": "error", "message": str(e), "logs": logs}), 500

    target_acc = next((a for a in all_accounts if a.get('email') == email), None)
    if not target_acc or not target_acc.get('api_key'): 
        return jsonify({"status": "error", "message": "API Key ko hợp lệ", "logs": logs}), 400

    sys_cfg = SystemConfig.query.first()
    proxies = None
    if sys_cfg and sys_cfg.proxy_ip and sys_cfg.proxy_port:
        p_url = f"http://{sys_cfg.proxy_user}:{sys_cfg.proxy_pass}@{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}" if sys_cfg.proxy_user else f"http://{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}"
        proxies = {"http": p_url, "https": p_url}

    allowed_payment_names = [p.strip().upper() for p in pttt_str.split(',') if p.strip()]
    valid_pids = []
    
    if allowed_payment_names:
        try:
            pay_headers = get_bybit_headers(target_acc['api_key'], target_acc['api_secret'], "{}")
            res_pay = requests.post("https://api.bybit.com/v5/p2p/user/payment/list", headers=pay_headers, data="{}", proxies=proxies, timeout=15).json()
            if str(res_pay.get("retCode", res_pay.get("ret_code"))) == "0":
                fetched_payments = res_pay.get("result", [])
                payments_by_name = {}
                for p in fetched_payments:
                    if str(p.get("id")) == "-1": continue
                    p_name = p.get("paymentConfigVo", {}).get("paymentName", "").strip().upper()
                    if p_name in allowed_payment_names:
                        if p_name not in payments_by_name:
                            payments_by_name[p_name] = []
                        payments_by_name[p_name].append(str(p["id"]))
                
                for p_name, ids in payments_by_name.items():
                    valid_pids.append(random.choice(ids))
                    
                if valid_pids:
                    logs.append(f"Đã dịch thành công Tên Ngân hàng sang ID thật: {valid_pids}")
            else:
                err = res_pay.get("retMsg") or res_pay.get("ret_msg") or json.dumps(res_pay)
                logs.append(f"Lỗi lấy danh sách PTTT từ Bybit: {err}")
        except Exception as e:
            logs.append(f"Lỗi gọi API lấy PTTT: {str(e)}")

    final_payment_ids = valid_pids[:5] if valid_pids else data.get('paymentIds', [])
    if not final_payment_ids:
        logs.append("Cảnh báo: Không thể map được ID phương thức thanh toán thật sự. Lệnh update có thể sẽ bị Bybit từ chối!")

    raw_prefs = data.get('tradingPreferenceSet', {})
    bybit_prefs = {}
    bool_keys = ["hasUnPostAd", "isKyc", "isEmail", "isMobile", "hasRegisterTime", "hasOrderFinishNumberDay30", "hasCompleteRateDay30", "hasNationalLimit"]
    
    for k, v in raw_prefs.items():
        if k in bool_keys:
            if str(v).lower() in ['true', '1', 'yes']: bybit_prefs[k] = "1"
            else: bybit_prefs[k] = "0"
        else: bybit_prefs[k] = str(v)

    payload = {
        "id": str(item_id),
        "priceType": "0",
        "premium": "",
        "price": str(data.get('price', '')),
        "minAmount": str(data.get('minAmount', '')),
        "maxAmount": str(data.get('maxAmount', '')),
        "quantity": str(data.get('quantity', '')),
        "paymentPeriod": str(data.get('paymentPeriod', '15')),
        "remark": str(data.get('remark', '')),
        "actionType": "MODIFY",
        "paymentIds": final_payment_ids,
        "tradingPreferenceSet": bybit_prefs
    }

    try:
        payload_str = json.dumps(payload)
        req_headers = get_bybit_headers(target_acc['api_key'], target_acc['api_secret'], payload_str)
        logs.append(f"Đang gửi lệnh Cập nhật lên Bybit...")
        res_bybit = requests.post("https://api.bybit.com/v5/p2p/item/update", headers=req_headers, data=payload_str, proxies=proxies, timeout=15).json()
        
        if str(res_bybit.get("retCode", res_bybit.get("ret_code"))) == "0":
            logs.append(f"Thành công: Đã cập nhật QC {item_id}.")
            return jsonify({"status": "success", "message": "Đã cập nhật", "logs": logs})
        else:
            err_msg = res_bybit.get('retMsg') or res_bybit.get('ret_msg') or json.dumps(res_bybit)
            logs.append(f"Thất bại: {err_msg}")
            return jsonify({"status": "error", "message": err_msg, "logs": logs})
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return jsonify({"status": "error", "message": str(e), "logs": logs}), 500

# COPY VÀ THÊM VÀO CUỐI FILE app.py (trước phần if __name__ == '__main__':)

@app.route('/api/turn_off_ads', methods=['POST'])
def turn_off_ads():
    data = request.json
    group = data.get('group')
    ad_type = data.get('type', 'all') # 'buy', 'sell', 'all'
    logs = []
    
    if not group:
        return jsonify({"status": "error", "message": "Thiếu thông tin nhóm", "logs": logs}), 400
        
    logs.append(f"Nhận lệnh tắt hàng loạt quảng cáo: {ad_type.upper()}")

    try:
        # Lấy API Keys từ server cũ
        headers_int = { 'X-Internal-Token': INTERNAL_SECRET_TOKEN }
        res_keys = requests.get(f"{OLD_APP_URL}/api/internal/get_keys?group={group}", headers=headers_int, timeout=10)
        if res_keys.status_code != 200:
            return jsonify({"status": "error", "message": "Lỗi lấy Key từ App Cũ", "logs": logs}), 500
        all_accounts = res_keys.json().get('accounts', [])
        
        # Lấy danh sách quảng cáo đang chạy trên sàn
        res_ads = requests.get(f"{OLD_APP_URL}/api/fetch_group_ads?group={group}", timeout=20)
        if res_ads.status_code != 200:
            return jsonify({"status": "error", "message": "Lỗi kéo danh sách QC từ App Cũ", "logs": logs}), 500
        all_ads = res_ads.json().get('ads', [])
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "logs": logs}), 500

    buy_accounts = [acc.email for acc in AccountRole.query.filter_by(role='buy').all()]
    sell_accounts = [acc.email for acc in AccountRole.query.filter_by(role='sell').all()]

    sys_cfg = SystemConfig.query.first()
    proxies = None
    if sys_cfg and sys_cfg.proxy_ip and sys_cfg.proxy_port:
        p_url = f"http://{sys_cfg.proxy_user}:{sys_cfg.proxy_pass}@{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}" if sys_cfg.proxy_user else f"http://{sys_cfg.proxy_ip}:{sys_cfg.proxy_port}"
        proxies = {"http": p_url, "https": p_url}

    success_count = 0
    fail_count = 0

    # Lọc ra các quảng cáo hợp lệ thuộc hệ thống
    target_ads = []
    for ad in all_ads:
        # Chỉ xử lý các quảng cáo đang online/hiển thị
        if str(ad.get('status', '0')) != "10": 
            continue
            
        email = ad.get('account_email')
        side = str(ad.get('side')) # 0 là Mua, 1 là Bán
        
        # Bỏ qua quảng cáo ngoài lề
        if side == '0':
            if email not in buy_accounts: continue # Nếu là QC Mua nhưng email ko nằm trong nhóm Buy -> Ngoài lề
            if ad_type == 'sell': continue # Đang yêu cầu tắt Bán mà lại là Mua -> Bỏ qua
        elif side == '1':
            if email not in sell_accounts: continue # Nếu là QC Bán nhưng email ko nằm trong nhóm Sell -> Ngoài lề
            if ad_type == 'buy': continue # Đang yêu cầu tắt Mua mà lại là Bán -> Bỏ qua
        else:
            continue
            
        target_ads.append(ad)

    if not target_ads:
        logs.append(f"Không tìm thấy Quảng Cáo {ad_type.upper()} nào thuộc hệ thống đang Online cần tắt.")
        return jsonify({"status": "success", "message": "Không có QC hợp lệ để tắt", "logs": logs})

    logs.append(f"Tìm thấy {len(target_ads)} QC hợp lệ để tắt. Đang xử lý...")

    for ad in target_ads:
        email = ad.get('account_email')
        item_id = str(ad.get('id'))
        
        target_acc = next((a for a in all_accounts if a.get('email') == email), None)
        if not target_acc or not target_acc.get('api_key'):
            logs.append(f"[{email}] Bỏ qua QC {item_id} vì Nick mất kết nối / mất API Key.")
            fail_count += 1
            continue
            
        try:
            payload_str = json.dumps({"itemId": item_id})
            req_headers = get_bybit_headers(target_acc['api_key'], target_acc['api_secret'], payload_str)
            res_bybit = requests.post("https://api.bybit.com/v5/p2p/item/cancel", headers=req_headers, data=payload_str, proxies=proxies, timeout=10).json()
            
            if str(res_bybit.get("retCode", res_bybit.get("ret_code"))) == "0":
                # Nếu là qc bán được tạo từ tool, ta xóa liên kết DB
                LinkedSellAd.query.filter_by(ad_id=item_id).delete()
                db.session.commit()
                
                logs.append(f"✅ Đã tắt thành công QC {item_id} (Nick: {email})")
                success_count += 1
            else:
                err_msg = res_bybit.get('retMsg') or res_bybit.get('ret_msg') or json.dumps(res_bybit)
                logs.append(f"❌ Bybit từ chối xóa QC {item_id}: {err_msg}")
                fail_count += 1
        except Exception as e:
            logs.append(f"❌ Lỗi mạng khi xóa QC {item_id}: {str(e)}")
            fail_count += 1

    logs.append(f"Hoàn tất: Tắt thành công {success_count} QC, Thất bại {fail_count} QC.")
    return jsonify({"status": "success", "message": f"Tắt {success_count} QC thành công", "logs": logs})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=True)
