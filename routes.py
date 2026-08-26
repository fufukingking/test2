import os

import pandas as pd
import psycopg
from psycopg.rows import dict_row
from psycopg import Cursor

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    jsonify,
)
from werkzeug.security import check_password_hash, generate_password_hash

from help import apology, login_required

bp = Blueprint("routes", __name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if "sslmode=" not in DATABASE_URL:
    separator = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{separator}sslmode=require"


class CompatibilityCursor(Cursor):
    def execute(self, query, params=None, *, prepare=None, binary=None):
        query = query.replace("?", "%s")
        return super().execute(query, params, prepare=prepare, binary=binary)


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        cursor_factory=CompatibilityCursor,
    )


# ============================================================
# LOGIN
# ============================================================

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        session.clear()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username:
            return apology("请输入用户名", 400)
        if not password:
            return apology("请输入密码", 400)

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        db.close()

        if user is None:
            return apology("用户名或密码错误", 403)
        if not check_password_hash(user["password_hash"], password):
            return apology("用户名或密码错误", 403)

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        flash("登录成功！")
        return redirect("/")

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ============================================================
# REGISTER
# ============================================================

@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")

        if not username:
            return apology("请输入用户名", 400)
        if password != confirmation:
            return apology("两次输入的密码不一致", 400)

        db = get_db()
        existing_user = db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()

        if existing_user:
            db.close()
            return apology("用户名已经存在", 400)

        try:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), "student"),
            )
            db.commit()
        except psycopg.Error as e:
            db.rollback()
            db.close()
            return apology(f"数据库错误: {e}", 500)

        db.close()
        flash("注册成功！")
        return redirect("/login")

    return render_template("register.html")


# ============================================================
# SECTIONS
# ============================================================

@bp.route("/sections")
@login_required
def sections():
    db = get_db()
    secs = db.execute(
        """
        SELECT sections.*, COUNT(vocabulary.id) AS vocabulary_count
        FROM sections
        LEFT JOIN vocabulary ON vocabulary.section_id = sections.id
        GROUP BY sections.id
        ORDER BY sections.title
        """
    ).fetchall()
    db.close()
    return render_template("sections.html", sections=secs)


@bp.route("/section/<int:section_id>")
@login_required
def section(section_id):
    db = get_db()
    sec = db.execute(
        "SELECT * FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    if sec is None:
        db.close()
        return apology("学习单元不存在", 404)

    vocabulary = db.execute(
        "SELECT * FROM vocabulary WHERE section_id = ? ORDER BY id", (section_id,)
    ).fetchall()
    db.close()
    return render_template("section.html", section=sec, vocabulary=vocabulary)


# ============================================================
# ADMIN
# ============================================================

@bp.route("/admin")
@login_required
def admin():
    if session.get("role") != "teacher":
        return apology("只有教师可以访问管理页面", 403)

    db = get_db()
    secs = db.execute(
        """
        SELECT sections.*, COUNT(vocabulary.id) AS vocabulary_count
        FROM sections
        LEFT JOIN vocabulary ON vocabulary.section_id = sections.id
        GROUP BY sections.id
        ORDER BY sections.title
        """
    ).fetchall()
    db.close()
    return render_template("admin/index.html", sections=secs)


@bp.route("/admin/section/create", methods=["GET", "POST"])
@login_required
def create_section():
    if session.get("role") != "teacher":
        return apology("只有教师可以执行此操作", 403)

    if request.method == "GET":
        return render_template("admin/create_section.html")

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()

    if not title:
        return apology("请输入单元名称", 400)
    if len(title) > 100:
        return apology("单元名称不能超过100个字符", 400)

    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO sections (title, description) VALUES (?, ?) RETURNING id",
            (title, description),
        )
        db.commit()
        section_id = cursor.fetchone()["id"]
    except psycopg.Error as e:
        db.rollback()
        db.close()
        return apology(f"数据库错误: {e}", 500)
    finally:
        try:
            db.close()
        except Exception:
            pass

    flash("学习单元已创建！")
    return redirect(f"/admin/section/{section_id}")


@bp.route("/admin/section/<int:section_id>/add", methods=["GET", "POST"])
@login_required
def add_vocabulary(section_id):
    if session.get("role") != "teacher":
        return apology("只有教师可以执行此操作", 403)

    db = get_db()
    sec = db.execute(
        "SELECT * FROM sections WHERE id = ?", (section_id,)
    ).fetchone()

    if sec is None:
        db.close()
        return apology("学习单元不存在", 404)

    if request.method == "POST":
        chinese = request.form.get("chinese", "").strip()
        pinyin = request.form.get("pinyin", "").strip()
        translation = request.form.get("translation", "").strip()
        relevance = request.form.get("relevance", "")

        if not chinese:
            db.close()
            return apology("请输入中文词汇", 400)
        if not translation:
            db.close()
            return apology("请输入翻译", 400)

        try:
            relevance = int(relevance)
            if relevance < 1:
                raise ValueError
        except (ValueError, TypeError):
            db.close()
            return apology("请输入有效的相关性分数", 400)

        try:
            db.execute(
                """INSERT INTO vocabulary
                (section_id, chinese, pinyin, translation, relevance)
                VALUES (?, ?, ?, ?, ?)""",
                (section_id, chinese, pinyin, translation, relevance),
            )
            db.commit()
        except psycopg.Error as e:
            db.rollback()
            db.close()
            return apology(f"数据库错误: {e}", 500)

        db.close()
        flash("词汇已添加！")
        return redirect(f"/admin/section/{section_id}")

    db.close()
    return render_template("admin/add_vocabulary.html", section=sec)


@bp.route("/admin/section/<int:section_id>")
@login_required
def admin_section(section_id):
    if session.get("role") != "teacher":
        return apology("只有教师可以执行此操作", 403)

    db = get_db()
    sec = db.execute(
        "SELECT * FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    if sec is None:
        db.close()
        return apology("学习单元不存在", 404)

    vocabulary = db.execute(
        "SELECT * FROM vocabulary WHERE section_id = ? ORDER BY id", (section_id,)
    ).fetchall()
    db.close()
    return render_template("admin/section.html", section=sec, vocabulary=vocabulary)


@bp.route("/admin/vocabulary/<int:vocabulary_id>/delete")
@login_required
def delete_vocabulary(vocabulary_id):
    if session.get("role") != "teacher":
        return apology("只有教师可以执行此操作", 403)

    db = get_db()
    vocab = db.execute(
        "SELECT * FROM vocabulary WHERE id = ?", (vocabulary_id,)
    ).fetchone()
    if vocab is None:
        db.close()
        return apology("词汇不存在", 404)

    section_id = vocab["section_id"]
    try:
        db.execute("DELETE FROM vocabulary WHERE id = ?", (vocabulary_id,))
        db.commit()
    except psycopg.Error as e:
        db.rollback()
        db.close()
        return apology(f"数据库错误: {e}", 500)

    db.close()
    flash("词汇已删除！")
    return redirect(f"/admin/section/{section_id}")


@bp.route("/admin/section/<int:section_id>/delete")
@login_required
def delete_section(section_id):
    if session.get("role") != "teacher":
        return apology("只有教师可以执行此操作", 403)

    db = get_db()
    sec = db.execute(
        "SELECT * FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    if sec is None:
        db.close()
        return apology("学习单元不存在", 404)

    try:
        db.execute("DELETE FROM sections WHERE id = ?", (section_id,))
        db.commit()
    except psycopg.Error as e:
        db.rollback()
        db.close()
        return apology(f"数据库错误: {e}", 500)

    db.close()
    flash("学习单元已删除！")
    return redirect("/admin")


# ============================================================
# LEADERBOARD
# ============================================================

@bp.route("/leaderboard")
@login_required
def leaderboard():
    db = get_db()
    lb = db.execute(
        """SELECT username, total_points FROM users
        WHERE role = 'student' ORDER BY total_points DESC"""
    ).fetchall()
    db.close()
    return render_template("leaderboard.html", leaderboard=lb)


# ============================================================
# MAKE TEACHER
# ============================================================

@bp.route("/make-teacher")
def make_teacher():
    db = get_db()
    db.execute(
        "UPDATE users SET role = 'teacher' WHERE username = ?", ("teacher",)
    )
    db.commit()
    db.close()
    return "User is now a teacher"


# ============================================================
# VOCABULARY PRACTICE
# ============================================================

@bp.route("/section/<int:section_id>/practice")
@login_required
def practice(section_id):
    db = get_db()
    sec = db.execute(
        "SELECT * FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    if sec is None:
        db.close()
        return apology("学习单元不存在", 404)

    vocabulary = db.execute(
        "SELECT * FROM vocabulary WHERE section_id = ? ORDER BY RANDOM() LIMIT 1",
        (section_id,),
    ).fetchone()
    db.close()

    if vocabulary is None:
        return apology("此单元还没有词汇", 400)

    return render_template("practice.html", section=sec, vocabulary=vocabulary)


@bp.route("/section/<int:section_id>/practice/point", methods=["POST"])
@login_required
def practice_point(section_id):
    db = get_db()
    sec = db.execute(
        "SELECT id FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    if sec is None:
        db.close()
        return jsonify({"error": "Section nicht gefunden"}), 404

    try:
        db.execute(
            """UPDATE users SET total_points = total_points + 1
            WHERE id = ? AND role = 'student'""",
            (session["user_id"],),
        )
        vocabulary = db.execute(
            "SELECT * FROM vocabulary WHERE section_id = ? ORDER BY RANDOM() LIMIT 1",
            (section_id,),
        ).fetchone()
        db.commit()
    except psycopg.Error as e:
        db.rollback()
        db.close()
        return jsonify({"error": str(e)}), 500

    db.close()

    if vocabulary is None:
        return jsonify({"error": "Keine Vokabeln vorhanden"}), 404

    return jsonify({
        "chinese": vocabulary["chinese"],
        "pinyin": vocabulary["pinyin"] or "",
        "translation": vocabulary["translation"],
    })


# ============================================================
# IMPORT VOCABULARY FROM EXCEL
# ============================================================

@bp.route("/admin/section/<int:section_id>/import-excel", methods=["GET", "POST"])
@login_required
def import_excel(section_id):
    if session.get("role") != "teacher":
        return apology("只有教师可以执行此操作", 403)

    db = get_db()
    sec = db.execute(
        "SELECT * FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    if sec is None:
        db.close()
        return apology("学习单元不存在", 404)

    if request.method == "GET":
        db.close()
        return render_template("admin/import_excel.html", section=sec)

    file = request.files.get("excel_file")
    if not file or file.filename == "":
        db.close()
        return apology("请选择一个 Excel 文件", 400)
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        db.close()
        return apology("请上传 Excel 文件", 400)

    try:
        df = pd.read_excel(file, sheet_name=0, header=None)
        imported = 0
        for value in df.iloc[:, 0]:
            if pd.isna(value):
                continue
            chinese = str(value).strip()
            if not chinese:
                continue
            db.execute(
                """INSERT INTO vocabulary
                (section_id, chinese, pinyin, translation, relevance)
                VALUES (?, ?, ?, ?, ?)""",
                (section_id, chinese, "", "", 1),
            )
            imported += 1
        db.commit()
    except Exception as e:
        db.rollback()
        db.close()
        return apology(f"Excel Import Fehler: {e}", 400)

    db.close()
    flash(f"{imported} Vokabeln erfolgreich importiert!")
    return redirect(f"/admin/section/{section_id}")

