import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, join_room, leave_room, emit

# --- APP CONFIGURATION ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-key-that-you-should-change'
# --- THE ONLY CHANGE IS ON THIS NEXT LINE ---
# We are now creating the database in the main project folder.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///projectmate.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# --- Create necessary folders ---
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
# The instance folder is no longer needed, but this is kept for safety.
try:
    os.makedirs(app.instance_path)
except OSError:
    pass

# --- EXTENSION INITIALIZATION ---
db = SQLAlchemy(app)
socketio = SocketIO(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'txt', 'py', 'js', 'html', 'css', 'json', 'xml', 'md'}

# --- DATABASE MODELS ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

collab_members = db.Table('collab_members',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('collab_room_id', db.Integer, db.ForeignKey('collaboration_room.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    skills = db.Column(db.String(300), default='')
    bio = db.Column(db.String(500), default='')
    social_links = db.Column(db.String(300), default='')
    projects = db.relationship('Project', backref='creator', lazy=True)
    requests_sent = db.relationship('JoinRequest', backref='requester', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    purpose = db.Column(db.Text, nullable=False)
    problem_statement = db.Column(db.Text, nullable=False)
    domain = db.Column(db.String(100))
    skills_required = db.Column(db.String(300))
    skills_you_have = db.Column(db.String(300))
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    requests = db.relationship('JoinRequest', backref='project', lazy=True, cascade="all, delete-orphan")
    collab_room = db.relationship('CollaborationRoom', backref='project', uselist=False, cascade="all, delete-orphan")

class JoinRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')

class CollaborationRoom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), unique=True, nullable=False)
    notes = db.Column(db.Text, default='')
    members = db.relationship('User', secondary=collab_members, lazy='subquery',
                              backref=db.backref('collab_rooms', lazy=True))
    files = db.relationship('UploadedFile', backref='room', lazy=True, cascade="all, delete-orphan")
    messages = db.relationship('Message', backref='room', lazy=True, cascade="all, delete-orphan")

class UploadedFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(150), nullable=False)
    original_filename = db.Column(db.String(150), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('collaboration_room.id'), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('collaboration_room.id'), nullable=False)
    sender = db.relationship('User')

# --- AUTHENTICATION ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            flash('Please check your login details and try again.', 'error')
            return redirect(url_for('login'))
        login_user(user)
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        phone_number = request.form.get('phone_number')
        user = User.query.filter_by(username=username).first()
        if user:
            flash('Username already exists.', 'error')
            return redirect(url_for('signup'))
        if email and email.strip() != '':
            user_by_email = User.query.filter_by(email=email).first()
            if user_by_email:
                flash('This email is already registered.', 'error')
                return redirect(url_for('signup'))
        new_user = User(
            username=username, 
            email=email if email else None,
            phone_number=phone_number if phone_number else None
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('dashboard'))
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- CORE ROUTES ---
@app.route('/')
def index():
    return redirect(url_for('explore'))

@app.route('/dashboard')
@login_required
def dashboard():
    my_projects = Project.query.filter_by(creator_id=current_user.id).all()
    joined_rooms = CollaborationRoom.query.filter(CollaborationRoom.members.any(id=current_user.id)).all()
    my_project_ids = [p.id for p in my_projects]
    joined_projects_rooms = [room for room in joined_rooms if room.project_id not in my_project_ids]
    return render_template('dashboard.html', my_projects=my_projects, joined_projects_rooms=joined_projects_rooms)

@app.route('/explore')
def explore():
    projects = Project.query.order_by(Project.id.desc()).all()
    return render_template('explore.html', projects=projects)

# --- USER PROFILE ROUTES ---
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.skills = request.form.get('skills')
        current_user.bio = request.form.get('bio')
        current_user.social_links = request.form.get('social_links')
        current_user.email = request.form.get('email')
        current_user.phone_number = request.form.get('phone_number')
        db.session.commit()
        flash('Your profile has been updated!', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html')

# --- PROJECT ROUTES ---
@app.route('/project/create', methods=['GET', 'POST'])
@login_required
def create_project():
    if request.method == 'POST':
        new_project = Project(
            title=request.form['title'], purpose=request.form['purpose'],
            problem_statement=request.form['problem_statement'], domain=request.form['domain'],
            skills_required=request.form['skills_required'], skills_you_have=request.form['skills_you_have'],
            creator_id=current_user.id
        )
        db.session.add(new_project)
        db.session.commit()
        flash('Project created successfully!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('create_project.html')

@app.route('/project/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_project(project_id):
    project = Project.query.get_or_404(project_id)
    if project.creator_id != current_user.id:
        flash('You can only edit your own projects.', 'error')
        return redirect(url_for('explore'))
    if request.method == 'POST':
        project.title = request.form['title']
        project.purpose = request.form['purpose']
        project.problem_statement = request.form['problem_statement']
        project.domain = request.form['domain']
        project.skills_required = request.form['skills_required']
        project.skills_you_have = request.form['skills_you_have']
        db.session.commit()
        flash('Project updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('edit_project.html', project=project)

@app.route('/project/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    if project.creator_id != current_user.id:
        flash('You can only delete your own projects.', 'error')
        return redirect(url_for('dashboard'))
    db.session.delete(project)
    db.session.commit()
    flash('Project deleted successfully.', 'success')
    return redirect(url_for('dashboard'))

# --- JOIN REQUEST ROUTES ---
@app.route('/project/<int:project_id>/request', methods=['POST'])
@login_required
def send_request(project_id):
    project = Project.query.get_or_404(project_id)
    if project.creator_id == current_user.id:
        flash("You can't request to join your own project.", 'error')
        return redirect(url_for('explore'))
    existing_request = JoinRequest.query.filter_by(requester_id=current_user.id, project_id=project_id).first()
    if existing_request:
        flash('You have already sent a request for this project.', 'info')
        return redirect(url_for('explore'))
    new_request = JoinRequest(requester_id=current_user.id, project_id=project_id)
    db.session.add(new_request)
    db.session.commit()
    flash('Your request to join has been sent!', 'success')
    return redirect(url_for('explore'))

@app.route('/requests')
@login_required
def view_requests():
    my_projects_ids = [p.id for p in current_user.projects]
    incoming_requests = JoinRequest.query.filter(
        JoinRequest.project_id.in_(my_projects_ids),
        JoinRequest.status == 'pending'
    ).all()
    return render_template('join_requests.html', requests=incoming_requests)

@app.route('/request/<int:request_id>/<action>', methods=['POST'])
@login_required
def handle_request(request_id, action):
    join_request = JoinRequest.query.get_or_404(request_id)
    project = join_request.project
    if project.creator_id != current_user.id:
        flash('Not authorized.', 'error')
        return redirect(url_for('view_requests'))
    if action == 'accept':
        if project.collab_room:
            flash('This project already has a collaborator.', 'error')
            join_request.status = 'rejected'
            db.session.commit()
            return redirect(url_for('view_requests'))
        
        join_request.status = 'accepted'
        new_room = CollaborationRoom(project_id=project.id)
        project_creator = User.query.get(project.creator_id)
        requesting_user = User.query.get(join_request.requester_id)
        new_room.members.append(project_creator)
        new_room.members.append(requesting_user)
        db.session.add(new_room)
        for req in project.requests:
            if req.status == 'pending':
                req.status = 'rejected'
        flash('Request accepted and collaboration room created!', 'success')
    elif action == 'reject':
        join_request.status = 'rejected'
        flash('Request rejected.', 'info')
    db.session.commit()
    return redirect(url_for('view_requests'))

# --- COLLABORATION ROOM ---
@app.route('/collab/<int:room_id>', methods=['GET', 'POST'])
@login_required
def collab_room(room_id):
    room = CollaborationRoom.query.get_or_404(room_id)
    if current_user not in room.members:
        flash('You do not have access to this room.', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        def allowed_file(filename):
            return '.' in filename and \
                   filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            new_file_record = UploadedFile(filename=filename, original_filename=file.filename, room_id=room.id) 
            db.session.add(new_file_record)
            db.session.commit()
            socketio.emit('new_file_added', {
                'filename': filename, 
                'original_filename': file.filename,
                'room': str(room_id)
            }, to=str(room_id))
            return jsonify({'success': True, 'filename': filename, 'original_filename': file.filename})
        else:
            return jsonify({'error': 'File type not allowed'}), 400
    previous_messages = Message.query.filter_by(room_id=room.id).order_by(Message.timestamp).all()
    return render_template('collab_room.html', room=room, messages=previous_messages)

# --- SOCKET.IO EVENTS ---
@socketio.on('join_room')
def on_join(data):
    room = data['room']
    join_room(room)

@socketio.on('text_update')
def on_text_update(data):
    room_id = data['room']
    room = CollaborationRoom.query.get(int(room_id))
    if room and current_user in room.members:
        room.notes = data['text']
        db.session.commit()
        emit('update_text', {'text': data['text']}, to=room_id, include_self=False)

@socketio.on('send_message')
def handle_send_message(data):
    room_id = data['room']
    room = CollaborationRoom.query.get(int(room_id))
    if room and current_user in room.members:
        current_time = datetime.now()
        new_message = Message(content=data['msg'], user_id=current_user.id, room_id=int(room_id), timestamp=current_time)
        db.session.add(new_message)
        db.session.commit()
        msg_data = {
            'msg': data['msg'],
            'username': current_user.username,
            'timestamp': current_time.strftime('%I:%M %p')
        }
        emit('new_message', msg_data, to=room_id)

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True)