"""Small offline activation, owner setup and sign-in screens."""
from pathlib import Path
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .db import UserError
from .licensing import license_status, decode_key, validate_license
from .security import validate_pin, SECURITY_QUESTIONS


class SecurityScreen(tk.Tk):
    def __init__(self, store, license_path):
        super().__init__()
        self.store, self.license_path = store, Path(license_path)
        self.result = False
        self.title('Sanitary Shop POS')
        self.geometry('540x650')
        self.resizable(True, True)
        self.configure(bg='#f6f8f7')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 11), background='#f6f8f7', foreground='#1f2937')
        style.configure('TFrame', background='#f6f8f7')
        style.configure('Card.TFrame', background='white')
        style.configure('TLabel', background='white')
        style.configure('TEntry', padding=10, fieldbackground='white', bordercolor='#cbd5d1')
        style.configure('Accent.TButton', padding=(18, 11), background='#087a55', foreground='white', bordercolor='#087a55', font=('Segoe UI', 11, 'bold'))
        style.map('Accent.TButton', background=[('active', '#16a36f')])
        self.canvas = tk.Canvas(self, bg='#f6f8f7', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.card = ttk.Frame(self.canvas, style='Card.TFrame', padding=28)
        self.card_window = self.canvas.create_window(20, 20, anchor='nw', window=self.card)
        self.canvas.bind('<Configure>', self.layout_card)
        self.card.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.bind('<MouseWheel>', lambda event: self.canvas.yview_scroll(int(-event.delta / 120), 'units'))
        self.protocol('WM_DELETE_WINDOW', self.destroy)

    def clear(self):
        self.unbind('<Return>')
        for widget in self.card.winfo_children():
            widget.destroy()
        self.canvas.yview_moveto(0)
        self.after_idle(self.fit_form)

    def layout_card(self, event):
        self.canvas.itemconfigure(self.card_window, width=max(260, event.width - 40))

    def fit_form(self):
        self.update_idletasks()
        width = min(560, self.winfo_screenwidth() - 60)
        height = min(self.card.winfo_reqheight() + 40, self.winfo_screenheight() - 110)
        self.geometry(f'{width}x{height}')
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def title_block(self, title, subtitle):
        tk.Label(self.card, text='SANITARY SHOP', bg='white', fg='#087a55', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        tk.Label(self.card, text=title, bg='white', fg='#14213d', font=('Segoe UI', 23, 'bold')).pack(anchor='w', pady=(7, 4))
        tk.Label(self.card, text=subtitle, bg='white', fg='#667085', justify='left', wraplength=340).pack(anchor='w', pady=(0, 22))

    def start(self):
        status = license_status(self.store, self.license_path)
        if not status['valid']:
            self.activation(status)
        elif not self.store.has_owner():
            self.owner_setup()
        else:
            self.login(status)
        self.mainloop()
        return self.result

    def activation(self, status):
        self.clear()
        self.title_block('Software activation', status.get('message') or 'Activate this computer with a signed license file.')
        tk.Label(self.card, text='Device ID', bg='white', fg='#475467', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        device = ttk.Entry(self.card)
        device.insert(0, status['device_id'])
        device.configure(state='readonly')
        device.pack(fill='x', pady=(4, 18))
        tk.Label(self.card, text='License file', bg='white', fg='#475467', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        selected = tk.StringVar()
        ttk.Entry(self.card, textvariable=selected).pack(fill='x', pady=(4, 8))
        def choose():
            path = filedialog.askopenfilename(parent=self, title='Choose signed license', filetypes=[('Sanitary Shop license', '*.lic *.license *.json')])
            if path:
                selected.set(path)
        ttk.Button(self.card, text='Choose license file', command=choose).pack(anchor='w')
        ttk.Label(self.card, text='Or paste your license key').pack(anchor='w', pady=(14, 4))
        key_entry = tk.Text(self.card, height=4, width=30, wrap='char', font=('Segoe UI', 10))
        key_entry.pack(fill='x')
        def activate():
            import json
            text = key_entry.get('1.0', 'end').strip()
            if text:
                document = decode_key(text)
            elif selected.get():
                try:
                    document = json.loads(Path(selected.get()).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    raise UserError('License file could not be read.') from None
            else:
                raise UserError('Choose a license file or paste your license key.')
            verified = validate_license(document, self.store.device_id())
            payload = dict(valid=True, kind='license', payload=verified, device_id=self.store.device_id())
            self.license_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.license_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(document), encoding='utf-8')
            temporary.replace(self.license_path)
            self.store.update_license_state(activated_at=__import__('datetime').datetime.now().isoformat(timespec='seconds'))
            self.store.audit('Activated license', payload['payload']['license_id'])
            self.owner_setup() if not self.store.has_owner() else self.login(payload)
        ttk.Button(self.card, text='Activate license', command=lambda: self.guard(activate), style='Accent.TButton').pack(fill='x', pady=(20, 8))
        if status['kind'] == 'none':
            ttk.Button(self.card, text='Start 14-day trial', command=lambda: self.start_trial()).pack(fill='x')

    def start_trial(self):
        from datetime import date
        self.store.update_license_state(trial_started=date.today().isoformat(), last_seen_date=date.today().isoformat())
        self.store.audit('Started trial', '14 days')
        self.owner_setup()

    def owner_setup(self):
        self.clear()
        self.title_block('Create shop owner', 'The owner account has full access. Keep this PIN private; there is no built-in master password.')
        name, pin, confirm = tk.StringVar(), tk.StringVar(), tk.StringVar()
        question, answer = tk.StringVar(value=SECURITY_QUESTIONS[0]), tk.StringVar()
        for label, value, hidden in (('Owner name', name, False), ('Create PIN', pin, True), ('Confirm PIN', confirm, True), ('Security question', question, False), ('Security answer', answer, True)):
            tk.Label(self.card, text=label, bg='white', fg='#475467', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(8, 3))
            (ttk.Combobox(self.card,textvariable=value,values=SECURITY_QUESTIONS,state='readonly') if label=='Security question' else ttk.Entry(self.card, textvariable=value, show='•' if hidden else '')).pack(fill='x')
        def create():
            if pin.get() != confirm.get():
                raise UserError('PIN confirmation does not match.')
            self.store.create_user(name.get(), 'OWNER', pin.get(), question.get(), answer.get())
            self.store.authenticate(self.store.users()[0]['id'], pin.get())
            self.result = True
            self.destroy()
        ttk.Button(self.card, text='Create owner account', command=lambda: self.guard(create), style='Accent.TButton').pack(fill='x', pady=(23, 0))

    def login(self, status):
        self.clear()
        trial_text = f"Trial · {status['remaining']} days remaining" if status['kind'] == 'trial' else 'Licensed · This PC'
        self.title_block('Welcome back', trial_text)
        users = self.store.users()
        selected = tk.StringVar(value=users[0]['name'])
        names = [row['name'] for row in users]
        tk.Label(self.card, text='User', bg='white', fg='#475467', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        ttk.Combobox(self.card, textvariable=selected, values=names, state='readonly').pack(fill='x', pady=(4, 15))
        pin = tk.StringVar()
        tk.Label(self.card, text='PIN', bg='white', fg='#475467', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        entry = ttk.Entry(self.card, textvariable=pin, show='•')
        entry.pack(fill='x', pady=(4, 22))
        def sign_in():
            person = next(row for row in self.store.users() if row['name'] == selected.get())
            self.store.authenticate(person['id'], pin.get())
            self.result = True
            self.destroy()
        ttk.Button(self.card, text='Login', command=lambda: self.guard(sign_in), style='Accent.TButton').pack(fill='x')
        ttk.Button(self.card, text='Forgot PIN?', command=lambda: self.forgot_pin(next(row for row in users if row['name'] == selected.get()), status)).pack(fill='x', pady=(8, 0))
        entry.focus_set()
        self.bind('<Return>', lambda _event: self.guard(sign_in))

    def forgot_pin(self, person, status):
        self.clear()
        self.title_block('Reset PIN', 'Answer your security question, then choose a new PIN.')
        configured = bool(person['security_question'])
        question_text = person['security_question'] if configured else 'No security question is configured. Ask the Owner to set one in Settings → Users & Privileges.'
        ttk.Label(self.card, text=question_text, wraplength=360).pack(anchor='w', pady=(8, 4))
        answer = tk.StringVar()
        ttk.Entry(self.card, textvariable=answer, show='•').pack(fill='x')
        pin, confirm = tk.StringVar(), tk.StringVar()
        for label, value in (('New PIN', pin), ('Confirm PIN', confirm)):
            ttk.Label(self.card, text=label).pack(anchor='w', pady=(8, 4))
            ttk.Entry(self.card, textvariable=value, show='•').pack(fill='x')
        def reset():
            if pin.get() != confirm.get():
                raise UserError('PIN confirmation does not match.')
            self.store.reset_pin_with_answer(person['id'], answer.get(), pin.get())
            messagebox.showinfo('PIN reset', 'Your PIN has been reset. Log in with your new PIN.', parent=self)
            self.login(status)
        ttk.Button(self.card, text='Reset PIN', command=lambda: self.guard(reset), style='Accent.TButton', state='normal' if configured else 'disabled').pack(fill='x', pady=12)
        ttk.Button(self.card, text='Back to login', command=lambda: self.login(status)).pack(fill='x')

    def recovery_request(self, user_id):
        from .recovery import create_request
        path = filedialog.asksaveasfilename(parent=self, title='Save owner recovery request', defaultextension='.json', initialfile='owner-recovery-request.json', filetypes=[('Recovery request', '*.json')])
        if path:
            request = create_request(self.store, user_id)
            Path(path).write_text(__import__('json').dumps(request, indent=2), encoding='utf-8')
            messagebox.showinfo('Recovery request saved', 'Send this file to your software vendor. The POS has no universal password or local master reset.', parent=self)

    def guard(self, action):
        try:
            action()
        except UserError as error:
            messagebox.showwarning('Please check', str(error), parent=self)
