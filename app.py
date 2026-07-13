import os
import sqlite3
import datetime
from flask import Flask, request, render_template_string, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'banchan_ultra_secret_key_2026')
DB_FILE = 'clock_system.db'

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

# Render 환경 실행 시 DB 초기화 강제
with app.app_context():
    init_db()

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

# 공통 레이아웃
def get_base_layout(content_html):
    return f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Banchan & Co. Staff Portal</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-50 text-gray-800 min-h-screen flex flex-col justify-between">
        <header class="bg-indigo-600 text-white shadow p-4 flex justify-between items-center">
            <a href="{ url_for('dashboard') }" class="text-xl font-bold flex items-center gap-2">
                🍱 Banchan & Co.
            </a>
            <div class="flex items-center gap-2">
                {{% if session.get('role') == 'admin' %}}
                    <span class="text-xs bg-amber-500 text-white font-bold px-2 py-1 rounded">관리자 모드</span>
                    <a href="{ url_for('admin_dashboard') }" class="text-xs bg-indigo-700 hover:bg-indigo-800 px-3 py-1.5 rounded text-white">관리 메뉴</a>
                    <a href="{ url_for('logout') }" class="text-xs bg-red-500 hover:bg-red-600 px-3 py-1.5 rounded text-white">로그아웃</a>
                {{% else %}}
                    <a href="{ url_for('admin_login') }" class="text-[10px] text-indigo-200 hover:text-white border border-indigo-400 px-2 py-1 rounded">관리자 로그인</a>
                {{% endif %}}
            </div>
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

# 1. 메인 대시보드 (로그인 없이 바로 직원 목록 제공)
@app.route('/')
@app.route('/dashboard')
def dashboard():
    with get_db() as conn:
        employees = conn.execute("SELECT id, full_name FROM users WHERE role != 'admin' ORDER BY full_name").fetchall()
        
        # 각 직원의 현재 상태 확인 (근무중인지 여부)
        status_dict = {}
        for emp in employees:
            last_log = conn.execute("SELECT clock_out FROM logs WHERE user_id = ? ORDER BY id DESC LIMIT 1", (emp['id'],)).fetchone()
            if last_log and last_log['clock_out'] is None:
                status_dict[emp['id']] = '근무 중'
            else:
                status_dict[emp['id']] = '퇴근 상태'

    dashboard_html = """
    <div class="max-w-2xl mx-auto text-center mt-6">
        <h2 class="text-2xl font-black text-gray-800 mb-2">출퇴근 기록기 (Clock Panel)</h2>
        <p class="text-sm text-gray-500 mb-8">본인의 이름을 선택한 후 출근/퇴근 버튼을 눌러주세요.</p>
        
        {% if not employees %}
            <div class="bg-gray-100 p-8 rounded-xl border border-dashed text-gray-500">
                등록된 직원이 없습니다. 우측 상단 관리자 메뉴에서 직원을 등록해 주세요.
            </div>
        {% else %}
            <div class="grid grid-cols-2 sm:grid-cols-3 gap-4">
                {% for emp in employees %}
                    <a href="{{ url_for('employee_panel', user_id=emp.id) }}" 
                       class="p-5 bg-white rounded-xl shadow-sm border hover:shadow-md hover:border-indigo-500 transition-all text-center flex flex-col justify-between items-center gap-2">
                        <span class="text-lg font-bold text-gray-700">{{ emp.full_name }}</span>
                        {% if status_dict[emp.id] == '근무 중' %}
                            <span class="text-xs bg-green-100 text-green-700 px-2.5 py-1 rounded-full font-bold animate-pulse">● 근무 중</span>
                        {% else %}
                            <span class="text-xs bg-gray-100 text-gray-400 px-2.5 py-1 rounded-full font-medium">퇴근함</span>
                        {% endif %}
                    </a>
                {% endfor %}
            </div>
        {% endif %}
    </div>
    """
    return render_template_string(get_base_layout(dashboard_html), employees=employees, status_dict=status_dict)

# 2. 직원 개별 패널 (이름 누르면 나오는 화면)
@app.route('/employee/<int:user_id>')
def employee_panel(user_id):
    with get_db() as conn:
        user = conn.execute("SELECT id, full_name FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return redirect(url_for('dashboard'))
        
        last_log = conn.execute("SELECT * FROM logs WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    
    current_status = '퇴근함'
    if last_log and last_log['clock_out'] is None:
        current_status = '근무 중'

    panel_html = """
    <div class="max-w-md mx-auto mt-10 bg-white p-8 rounded-2xl shadow-lg border text-center">
        <h2 class="text-3xl font-extrabold text-indigo-900 mb-2">{{ user.full_name }}</h2>
        <div class="inline-block px-4 py-1.5 rounded-full text-xs font-bold mb-8 
            {% if current_status == '근무 중' %} bg-green-100 text-green-700 {% else %} bg-gray-100 text-gray-500 {% endif %}">
            현재 상태: {{ current_status }}
        </div>
        
        <form action="{{ url_for('clock_action', user_id=user.id) }}" method="POST" class="space-y-4">
            {% if current_status == '퇴근함' %}
                <button type="submit" name="action" value="in" 
                        class="w-full py-6 bg-indigo-600 hover:bg-indigo-700 text-white text-xl font-black rounded-2xl shadow-lg transition-all transform active:scale-95">
                    🚀 출근하기 (Clock In)
                </button>
            {% else %}
                <button type="submit" name="action" value="out" 
                        class="w-full py-6 bg-red-600 hover:bg-red-700 text-white text-xl font-black rounded-2xl shadow-lg transition-all transform active:scale-95">
                    🛑 퇴근하기 (Clock Out)
                </button>
            {% endif %}
        </form>
        
        <a href="{{ url_for('dashboard') }}" class="block mt-6 text-sm text-gray-400 hover:text-gray-600">취소하고 메인으로 돌아가기</a>
    </div>
    """
    return render_template_string(get_base_layout(panel_html), user=user, current_status=current_status)

# 3. 출퇴근 기록 처리 (기록 완료 후 즉시 메인화면 복귀)
@app.route('/employee/<int:user_id>/clock', methods=['POST'])
def clock_action(user_id):
    action = request.form.get('action')
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with get_db() as conn:
        user = conn.execute("SELECT full_name FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return redirect(url_for('dashboard'))
            
        last_log = conn.execute("SELECT * FROM logs WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        
        if action == 'in':
            conn.execute("INSERT INTO logs (user_id, clock_in) VALUES (?, ?)", (user_id, now_str))
            flash(f'🔔 {user["full_name"]}님 출근 완료 ({datetime.datetime.now().strftime("%I:%M %p")})', 'success')
        elif action == 'out' and last_log:
            conn.execute("UPDATE logs SET clock_out = ? WHERE id = ?", (now_str, last_log['id']))
            flash(f'🔔 {user["full_name"]}님 퇴근 완료 ({datetime.datetime.now().strftime("%I:%M %p")})', 'success')
        conn.commit()
        
    return redirect(url_for('dashboard'))

# 4. 관리자 로그인
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ? AND role = 'admin'", (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            return redirect(url_for('admin_dashboard'))
        flash('관리자 로그인 실패', 'error')
        
    admin_login_html = """
    <div class="max-w-md mx-auto mt-12 bg-white p-8 rounded-lg shadow-md border">
        <h2 class="text-2xl font-bold mb-6 text-center text-gray-700">⚙️ 관리자 로그인</h2>
        <form action="{{ url_for('admin_login') }}" method="POST" class="space-y-4">
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
    """
    return render_template_string(get_base_layout(admin_login_html))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('dashboard'))

# 5. 관리자 대시보드 (비밀번호 변경 및 관리 통합)
@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
        
    periods = get_recent_pay_periods()
    selected_period_str = request.args.get('period', periods[1][0].strftime('%Y-%m-%d'))
    p_start = datetime.datetime.strptime(selected_period_str, '%Y-%m-%d').date()
    p_end = p_start + datetime.timedelta(days=13)
    
    with get_db() as conn:
        all_users = conn.execute("SELECT id, username, full_name, hourly_rate FROM users WHERE role != 'admin'").fetchall()
        payroll_summary = []
        for user in all_users:
            logs = conn.execute("SELECT clock_in, clock_out FROM logs WHERE user_id = ? AND date(clock_in) >= ? AND date(clock_in) <= ?", (user['id'], p_start.strftime('%Y-%m-%d'), p_end.strftime('%Y-%m-%d'))).fetchall()
            u_hours = 0.0
            for log in logs:
                if log['clock_out']:
                    u_hours += (datetime.datetime.strptime(log['clock_out'], '%Y-%m-%d %H:%M:%S') - datetime.datetime.strptime(log['clock_in'], '%Y-%m-%d %H:%M:%S')).total_seconds() / 3600.0
            payroll_summary.append({
                'id': user['id'],
                'full_name': user['full_name'],
                'hourly_rate': user['hourly_rate'],
                'total_hours': u_hours,
                'total_pay': u_hours * user['hourly_rate']
            })
            
    admin_html = """
    <div class="mb-8 flex justify-between items-center">
        <h2 class="text-2xl font-bold text-gray-800">🛠️ 관리자 패널</h2>
        <a href="{{ url_for('dashboard') }}" class="text-sm bg-gray-200 hover:bg-gray-300 px-4 py-2 rounded">출퇴근 화면으로</a>
    </div>
    
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="bg-white p-6 rounded-xl shadow-sm border lg:col-span-2">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-lg font-bold text-gray-700">급여 정산 기간 (수 ~ 화)</h3>
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
                <thead class="bg-gray-50 text-gray-600 text-xs">
                    <tr>
                        <th class="p-3">직원 이름</th>
                        <th class="p-3">지정 시급</th>
                        <th class="p-3">총 근무 시간</th>
                        <th class="p-3 text-right">정산 급여</th>
                    </tr>
                </thead>
                <tbody class="divide-y">
                    {% for row in payroll_summary %}
                    <tr>
                        <td class="p-3 font-bold">{{ row.full_name }}</td>
                        <td class="p-3">${{ "%.2f"|format(row.hourly_rate) }}</td>
                        <td class="p-3 font-semibold text-indigo-700">{{ "%.2f"|format(row.total_hours) }} hrs</td>
                        <td class="p-3 text-right font-bold text-green-700">${{ "%.2f"|format(row.total_pay) }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="space-y-6">
            <div class="bg-white p-6 rounded-xl shadow-sm border">
                <h3 class="text-md font-bold mb-4 text-gray-700">➕ 신규 직원 등록</h3>
                <form action="{{ url_for('add_user') }}" method="POST" class="space-y-3">
                    <input type="text" name="username" placeholder="아이디" required class="w-full p-2 border text-sm rounded">
                    <input type="password" name="password" placeholder="비밀번호" required class="w-full p-2 border text-sm rounded">
                    <input type="text" name="full_name" placeholder="직원 실명" required class="w-full p-2 border text-sm rounded">
                    <input type="number" step="0.01" name="hourly_rate" placeholder="시급 ($)" required class="w-full p-2 border text-sm rounded" value="15.00">
                    <button type="submit" class="w-full py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded text-sm shadow">등록하기</button>
                </form>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm border">
                <h3 class="text-md font-bold mb-4 text-rose-700">🔐 비밀번호 직접 변경</h3>
                <form action="{{ url_for('change_password') }}" method="POST" class="space-y-3">
                    <div>
                        <label class="block text-xs text-gray-500 mb-1">대상 선택</label>
                        <select name="target_user_id" class="w-full p-2 border text-sm rounded">
                            <option value="admin">관리자 계정 (admin)</option>
                            {% for row in payroll_summary %}
                                <option value="{{ row.id }}">{{ row.full_name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <input type="password" name="new_password" placeholder="새 비밀번호 입력" required class="w-full p-2 border text-sm rounded">
                    </div>
                    <button type="submit" class="w-full py-2 bg-rose-600 hover:bg-rose-700 text-white font-bold rounded text-sm shadow">비밀번호 변경 적용</button>
                </form>
            </div>
        </div>
    </div>
    """
    return render_template_string(
        get_base_layout(admin_html),
        periods=periods,
        selected_period_str=selected_period_str,
        payroll_summary=payroll_summary
    )

# 6. 직원 등록 처리
@app.route('/admin/user/add', methods=['POST'])
def add_user():
    if session.get('role') != 'admin': 
        return redirect(url_for('dashboard'))
        
    hashed_pw = generate_password_hash(request.form['password'])
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO users (username, password, full_name, hourly_rate) VALUES (?, ?, ?, ?)", 
                (request.form['username'], hashed_pw, request.form['full_name'], float(request.form['hourly_rate']))
            )
            conn.commit()
            flash(f'[{request.form["full_name"]}] 직원이 등록되었습니다.', 'success')
        except sqlite3.IntegrityError:
            flash('오류: 이미 존재하는 아이디입니다.', 'error')
    return redirect(url_for('admin_dashboard'))

# 7. 비밀번호 수정 처리
@app.route('/admin/user/change-password', methods=['POST'])
def change_password():
    if session.get('role') != 'admin': 
        return redirect(url_for('dashboard'))
        
    target_id = request.form.get('target_user_id')
    new_pw = request.form.get('new_password')
    hashed_pw = generate_password_hash(new_pw)
    
    with get_db() as conn:
        if target_id == 'admin':
            conn.execute("UPDATE users SET password = ? WHERE role = 'admin'", (hashed_pw,))
            flash('관리자(admin) 비밀번호가 안전하게 변경되었습니다.', 'success')
        else:
            conn.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_pw, int(target_id)))
            flash('해당 직원의 비밀번호가 성공적으로 재설정되었습니다.', 'success')
        conn.commit()
        
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
