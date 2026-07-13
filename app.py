import os
import sqlite3
import datetime
from flask import Flask, request, render_template_string, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'banchan_ultra_secret_key_2026')
DB_FILE = 'clock_system.db'

# 📍 [필수 변경] 매장 와이파이 이름 (대소문자 구분 필수)
STORE_WIFI_NAME = "home_5G" 

# 2주 정산 기준점: 2026년 1월 7일 (수요일)
ANCHOR_DATE = datetime.date(2026, 1, 7)

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                full_name TEXT NOT NULL,
                hourly_rate REAL NOT NULL DEFAULT 15.00,
                role TEXT NOT NULL DEFAULT 'employee'
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                clock_in TEXT NOT NULL,
                clock_out TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        admin = conn.execute("SELECT * FROM users WHERE role = 'admin'").fetchone()
        if not admin:
            hashed_pw = generate_password_hash('admin1234')
            conn.execute(
                "INSERT INTO users (username, password, full_name, hourly_rate, role) VALUES (?, ?, ?, ?, ?)",
                ('admin', hashed_pw, 'Manager', 0.0, 'admin')
            )
        conn.commit()

def get_pay_period_range(date_obj):
    if isinstance(date_obj, datetime.datetime):
        date_obj = date_obj.date()
    days_since = (date_obj - ANCHOR_DATE).days
    period_num = days_since // 14
    start = ANCHOR_DATE + datetime.timedelta(days=period_num * 14)
    end = start + datetime.timedelta(days=13)
    return start, end

def get_recent_pay_periods(n=6):
    today = datetime.date.today()
    current_start, _ = get_pay_period_range(today)
    periods = []
    for i in range(-n + 2, 2):
        start = current_start + datetime.timedelta(days=i * 14)
        end = start + datetime.timedelta(days=13)
        periods.append((start, end))
    return sorted(periods, reverse=True)

# --- 에러가 없는 완벽한 인라인 HTML 구조 정의 ---
def render_page(content_html):
    base_html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Banchan & Co. Staff</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-50 text-gray-800 min-h-screen flex flex-col justify-between">
        <header class="bg-indigo-600 text-white shadow p-4 flex justify-between items-center">
            <h1 class="text-xl font-bold">Banchan & Co. Portal</h1>
            {{% if session.get('user_id') %}}
            <div class="flex items-center gap-4">
                <span class="text-sm font-medium">{{{{ session['full_name'] }}}}님</span>
                <a href="{ url_for('logout') }" class="text-xs bg-indigo-700 hover:bg-indigo-800 px-3 py-1.5 rounded">로그아웃</a>
            </div>
            {{% endif %}}
        </header>
        
        <main class="flex-grow p-4 max-w-4xl mx-auto w-full">
            {{% with messages = get_flashed_messages(with_categories=true) %}}
              {{% if messages %}}
                {{% for category, message in messages %}}
                  <div class="p-4 mb-4 text-sm rounded {{% if category == 'error' %}}bg-red-100 text-red-700{{% else %}}bg-green-100 text-green-700{{% endif %}}">
                    {{{{ message }}}}
                  </div>
                {{% endfor %}}
              {{% endif %}}
            {{% endwith %}}
            
            {content_html}
        </main>
        <footer class="text-center p-4 text-xs text-gray-400 border-t mt-8">
            &copy; 2026 Banchan & Co. All Rights Reserved.
        </footer>
    </body>
    </html>
    """
    return base_html

LOGIN_HTML = render_page("""
<div class="max-w-md mx-auto mt-12 bg-white p-8 rounded-lg shadow-md border">
    <h2 class="text-2xl font-bold mb-6 text-center text-gray-700">직원 로그인</h2>
    <form action="{{ url_for('login') }}" method="POST" class="space-y-4">
        <div>
            <label class="block text-sm font-semibold text-gray-600 mb-1">아이디</label>
            <input type="text" name="username" required class="w-full p-2.5 border rounded focus:ring-2 focus:ring-indigo-500 outline-none">
        </div>
        <div>
            <label class="block text-sm font-semibold text-gray-600 mb-1">비밀번호</label>
            <input type="password" name="password" required class="w-full p-2.5 border rounded focus:ring-2 focus:ring-indigo-500 outline-none">
        </div>
        <button type="submit" class="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded shadow transition">로그인</button>
    </form>
</div>
""")

DASHBOARD_HTML = render_page("""
<div class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <div class="bg-white p-6 rounded-lg shadow border md:col-span-1 text-center flex flex-col justify-between">
        <div>
            <h3 class="text-lg font-bold mb-2">근무 상태</h3>
            <div class="inline-block px-4 py-2 rounded-full text-sm font-bold mb-4 
                {% if current_status == '근무 중' %} bg-green-100 text-green-700 {% else %} bg-gray-100 text-gray-600 {% endif %}">
                {{ current_status }}
            </div>
        </div>
        
        <form action="{{ url_for('clock') }}" method="POST" id="clockForm" class="space-y-3">
            {% if current_status == '퇴근함' or current_status == '기록 없음' %}
                <button type="submit" name="action" value="in" class="w-full py-4 bg-indigo-600 hover:bg-indigo-700 text-white text-lg font-bold rounded-lg shadow-lg">
                    🚀 출근하기 (Clock In)
                </button>
            {% else %}
                <button type="submit" name="action" value="out" class="w-full py-4 bg-red-600 hover:bg-red-700 text-white text-lg font-bold rounded-lg shadow-lg">
                    🛑 퇴근하기 (Clock Out)
                </button>
            {% endif %}
        </form>
        {% if session.get('role') == 'admin' %}
            <a href="{{ url_for('admin_dashboard') }}" class="block mt-4 text-sm text-indigo-600 hover:underline">👉 관리자 페이지</a>
        {% endif %}
    </div>

    <div class="bg-white p-6 rounded-lg shadow border md:col-span-2">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-bold">내 근무 시간표</h3>
            <span class="text-xs text-gray-500">정산주기: {{ period_start.strftime('%m/%d') }} ~ {{ period_end.strftime('%m/%d') }}</span>
        </div>
        <div class="bg-indigo-50 p-4 rounded-lg flex justify-between mb-6 text-sm">
            <div>
                <p class="text-gray-500">정산기간 누적</p>
                <p class="text-xl font-bold text-indigo-700">{{ "%.2f"|format(total_hours) }} 시간</p>
            </div>
            <div class="text-right">
                <p class="text-gray-500">예상 지급액 (시급: ${{ "%.2f"|format(hourly_rate) }})</p>
                <p class="text-xl font-bold text-gray-800">${{ "%.2f"|format(total_pay) }}</p>
            </div>
        </div>
        <div class="overflow-x-auto">
            <table class="w-full text-sm text-left">
                <thead class="bg-gray-100 text-gray-600 uppercase text-xs">
                    <tr>
                        <th class="p-3">날짜</th>
                        <th class="p-3">출근</th>
                        <th class="p-3">퇴근</th>
                        <th class="p-3 text-right">시간</th>
                    </tr>
                </thead>
                <tbody class="divide-y">
                    {% for log in logs %}
                    <tr>
                        <td class="p-3 font-medium">{{ log.date }}</td>
                        <td class="p-3 text-gray-600">{{ log.in_time }}</td>
                        <td class="p-3 text-gray-600">{{ log.out_time or '근무중' }}</td>
                        <td class="p-3 text-right font-semibold {% if not log.out_time %}text-green-600{% endif %}">
                            {{ "%.2f"|format(log.hours) if log.hours else '-' }}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
""")

ADMIN_HTML = render_page("""
<div class="mb-8 flex justify-between items-center">
    <h2 class="text-2xl font-bold text-gray-800">🛠️ 관리자 대시보드</h2>
    <a href="{{ url_for('dashboard') }}" class="text-sm bg-gray-200 hover:bg-gray-300 px-4 py-2 rounded">출퇴근 화면으로</a>
</div>
<div class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <div class="bg-white p-6 rounded-lg shadow border md:col-span-2">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-bold">정산 기간별 요약 (수 ~ 화)</h3>
            <form method="GET" action="{{ url_for('admin_dashboard') }}" id="periodForm">
                <select name="period" onchange="document.getElementById('periodForm').submit()" class="border p-1.5 text-sm rounded">
                    {% for start, end in periods %}
                        <option value="{{ start.strftime('%Y-%m-%d') }}" {% if start.strftime('%Y-%m-%d') == selected_period_str %}selected{% endif %}>
                            {{ start.strftime('%Y/%m/%d') }} ~ {{ end.strftime('%Y/%m/%d') }}
                        </option>
                    {% endfor %}
                </select>
            </form>
        </div>
        <table class="w-full text-sm text-left">
            <thead class="bg-gray-100 text-gray-600 text-xs">
                <tr><th class="p-3">직원 이름</th><th class="p-3">지정 시급</th><th class="p-3">총 근무 시간</th><th class="p-3 text-right">총 정산 급여</th></tr>
            </thead>
            <tbody class="divide-y">
                {% for row in payroll_summary %}
                <tr>
                    <td class="p-3 font-bold">{{ row.full_name }}</td>
                    <td class="p-3">${{ "%.2f"|format(row.hourly_rate) }}</td>
                    <td class="p-3 font-semibold text-indigo-700">{{ "%.2f"|format(row.total_hours) }} hrs</td>
                    <td class="p-3 text-right font-bold">${{ "%.2f"|format(row.total_pay) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    <div class="bg-white p-6 rounded-lg shadow border">
        <h3 class="text-lg font-bold mb-4">직원 추가</h3>
        <form action="{{ url_for('add_user') }}" method="POST" class="space-y-3">
            <input type="text" name="username" placeholder="아이디" required class="w-full p-2 border text-sm rounded">
            <input type="password" name="password" placeholder="비밀번호" required class="w-full p-2 border text-sm rounded">
            <input type="text" name="full_name" placeholder="직원이름" required class="w-full p-2 border text-sm rounded">
            <input type="number" step="0.01" name="hourly_rate" placeholder="시급 ($)" required class="w-full p-2 border text-sm rounded" value="15.00">
            <button type="submit" class="w-full py-2 bg-indigo-600 text-white font-bold rounded">직원 등록</button>
        </form>
    </div>
</div>
""")

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            return redirect(url_for('dashboard'))
        flash('로그인 실패', 'error')
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    today = datetime.date.today()
    period_start, period_end = get_pay_period_range(today)
    
    with get_db() as conn:
        last_log = conn.execute("SELECT * FROM logs WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        db_logs = conn.execute(
            "SELECT id, clock_in, clock_out FROM logs WHERE user_id = ? AND date(clock_in) >= ? AND date(clock_in) <= ? ORDER BY clock_in DESC",
            (user_id, period_start.strftime('%Y-%m-%d'), period_end.strftime('%Y-%m-%d'))
        ).fetchall()
        user_info = conn.execute("SELECT hourly_rate FROM users WHERE id = ?", (user_id,)).fetchone()
    
    current_status = '퇴근함'
    if last_log and last_log['clock_out'] is None:
        current_status = '근무 중'

    processed_logs = []
    total_hours = 0.0
    for log in db_logs:
        in_dt = datetime.datetime.strptime(log['clock_in'], '%Y-%m-%d %H:%M:%S')
        hours = None
        out_str = None
        if log['clock_out']:
            out_dt = datetime.datetime.strptime(log['clock_out'], '%Y-%m-%d %H:%M:%S')
            hours = (out_dt - in_dt).total_seconds() / 3600.0
            total_hours += hours
            out_str = out_dt.strftime('%I:%M %p')
            
        processed_logs.append({
            'date': in_dt.strftime('%m/%d (%a)'),
            'in_time': in_dt.strftime('%I:%M %p'),
            'out_time': out_str,
            'hours': hours
        })
        
    return render_template_string(
        DASHBOARD_HTML,
        current_status=current_status,
        logs=processed_logs,
        period_start=period_start,
        period_end=period_end,
        total_hours=total_hours,
        hourly_rate=user_info['hourly_rate'],
        total_pay=total_hours * user_info['hourly_rate']
    )

@app.route('/clock', methods=['POST'])
def clock():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    action = request.form.get('action')
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with get_db() as conn:
        last_log = conn.execute("SELECT * FROM logs WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if action == 'in':
            conn.execute("INSERT INTO logs (user_id, clock_in) VALUES (?, ?)", (user_id, now_str))
            flash('출근 완료되었습니다.', 'success')
        elif action == 'out' and last_log:
            conn.execute("UPDATE logs SET clock_out = ? WHERE id = ?", (now_str, last_log['id']))
            flash('퇴근 완료되었습니다.', 'success')
        conn.commit()
    return redirect(url_for('dashboard'))

@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    periods = get_recent_pay_periods()
    selected_period_str = request.args.get('period', periods[1][0].strftime('%Y-%m-%d'))
    p_start = datetime.datetime.strptime(selected_period_str, '%Y-%m-%d').date()
    p_end = p_start + datetime.timedelta(days=13)
    
    with get_db() as conn:
        all_users = conn.execute("SELECT id, full_name, hourly_rate FROM users WHERE role != 'admin'").fetchall()
        payroll_summary = []
        for user in all_users:
            logs = conn.execute("SELECT clock_in, clock_out FROM logs WHERE user_id = ? AND date(clock_in) >= ? AND date(clock_in) <= ?", (user['id'], p_start.strftime('%Y-%m-%d'), p_end.strftime('%Y-%m-%d'))).fetchall()
            u_hours = 0.0
            for log in logs:
                if log['clock_out']:
                    u_hours += (datetime.datetime.strptime(log['clock_out'], '%Y-%m-%d %H:%M:%S') - datetime.datetime.strptime(log['clock_in'], '%Y-%m-%d %H:%M:%S')).total_seconds() / 3600.0
            payroll_summary.append({'full_name': user['full_name'], 'hourly_rate': user['hourly_rate'], 'total_hours': u_hours, 'total_pay': u_hours * user['hourly_rate']})
    return render_template_string(ADMIN_HTML, periods=periods, selected_period_str=selected_period_str, payroll_summary=payroll_summary)

@app.route('/admin/user/add', methods=['POST'])
def add_user():
    if session.get('role') != 'admin': return redirect(url_for('dashboard'))
    hashed_pw = generate_password_hash(request.form['password'])
    with get_db() as conn:
        conn.execute("INSERT INTO users (username, password, full_name, hourly_rate) VALUES (?, ?, ?, ?)", (request.form['username'], hashed_pw, request.form['full_name'], float(request.form['hourly_rate'])))
        conn.commit()
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
