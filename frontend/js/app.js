/**
 * Gravity SDN — Core Application Logic
 * Router, API Client, Auth, and State Management
 */

const App = {
    state: {
        token: localStorage.getItem('gravity_token') || null,
        user: (() => {
            try {
                const u = localStorage.getItem('gravity_user');
                return (u && u !== 'undefined') ? JSON.parse(u) : null;
            } catch(e) { return null; }
        })(),
        currentPanel: window.location.hash.slice(1) || 'dashboard',
        alarms: [],
        devices: []
    },

    init() {
        this.cacheDOM();
        this.bindEvents();
        this.checkAuth();
    },

    cacheDOM() {
        this.dom = {
            app: document.getElementById('app'),
            loginOverlay: document.getElementById('login-overlay'),
            loginForm: document.getElementById('login-form'),
            loginError: document.getElementById('login-error'),
            sidebar: document.getElementById('sidebar'),
            sidebarToggle: document.getElementById('sidebar-toggle'),
            navItems: document.querySelectorAll('.nav-item'),
            panels: document.querySelectorAll('.panel'),
            pageTitle: document.getElementById('page-title'),
            userName: document.getElementById('user-name'),
            logoutBtn: document.getElementById('logout-btn'),
            toastContainer: document.getElementById('toast-container'),
            alarmBadge: document.getElementById('alarm-badge')
        };
    },

    bindEvents() {
        // Navigation
        window.addEventListener('hashchange', () => this.handleNavigation());
        
        // Sidebar Toggle
        this.dom.sidebarToggle.addEventListener('click', () => {
            this.dom.sidebar.classList.toggle('collapsed');
        });

        // Login / Logout
        this.dom.loginForm.addEventListener('submit', (e) => this.handleLogin(e));
        this.dom.logoutBtn.addEventListener('click', () => this.logout());

        // Global refresh
        document.getElementById('refresh-btn')?.addEventListener('click', () => {
            this.refreshCurrentPanel();
        });
    },

    // ── Authentication ───────────────────────────────────────────────────────

    checkAuth() {
        if (this.state.token) {
            this.showApp();
            // Validate token...
            this.dom.userName.textContent = this.state.user ? this.state.user.username : 'admin';
            this.handleNavigation();
            this.startPolling();
        } else {
            this.showLogin();
        }
    },

    async handleLogin(e) {
        e.preventDefault();
        const username = document.getElementById('login-username').value;
        const password = document.getElementById('login-password').value;
        const btn = document.getElementById('login-btn');
        
        btn.textContent = 'Authenticating...';
        btn.disabled = true;
        this.dom.loginError.textContent = '';

        try {
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);

            const response = await fetch('/api/v1/auth/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Authentication failed');
            }

            const data = await response.json();
            this.loginSuccess(data.access_token, data.user);
        } catch (error) {
            this.dom.loginError.textContent = error.message;
            btn.disabled = false;
            btn.textContent = 'Sign In';
        }
    },

    loginSuccess(token, user) {
        this.state.token = token;
        this.state.user = user;
        localStorage.setItem('gravity_token', token);
        localStorage.setItem('gravity_user', JSON.stringify(user));
        
        this.dom.userName.textContent = user.username;
        this.showApp();
        this.handleNavigation();
        this.startPolling();
        this.showToast('Login successful', 'Welcome to Gravity SDN', 'success');
    },

    logout() {
        this.state.token = null;
        this.state.user = null;
        localStorage.removeItem('gravity_token');
        localStorage.removeItem('gravity_user');
        this.stopPolling();
        this.showLogin();
    },

    showLogin() {
        this.dom.app.classList.add('hidden');
        this.dom.loginOverlay.classList.remove('hidden');
    },

    showApp() {
        this.dom.loginOverlay.classList.add('hidden');
        this.dom.app.classList.remove('hidden');
    },

    // ── Navigation & Routing ─────────────────────────────────────────────────

    handleNavigation() {
        let hash = window.location.hash.slice(1);
        if (!hash) hash = 'dashboard';
        
        this.state.currentPanel = hash;

        // Update active nav item
        this.dom.navItems.forEach(item => {
            if (item.dataset.panel === hash) {
                item.classList.add('active');
                this.dom.pageTitle.textContent = item.querySelector('.nav-label').textContent;
            } else {
                item.classList.remove('active');
            }
        });

        // Show panel
        this.dom.panels.forEach(panel => {
            if (panel.id === `panel-${hash}`) {
                panel.classList.add('active');
                this.loadPanel(hash);
            } else {
                panel.classList.remove('active');
            }
        });
    },

    async loadPanel(panelName) {
        const panelClass = window[`${panelName.charAt(0).toUpperCase() + panelName.slice(1)}Panel`];
        if (panelClass && typeof panelClass.init === 'function') {
            await panelClass.init();
        }
    },

    refreshCurrentPanel() {
        this.loadPanel(this.state.currentPanel);
        this.showToast('Manual Refresh', 'Data refreshed from server', 'info');
    },

    // ── API Client ───────────────────────────────────────────────────────────

    async apiGet(endpoint) {
        return this.apiCall(endpoint, 'GET');
    },

    async apiPost(endpoint, data) {
        return this.apiCall(endpoint, 'POST', data);
    },

    async apiPut(endpoint, data) {
        return this.apiCall(endpoint, 'PUT', data);
    },

    async apiDelete(endpoint) {
        return this.apiCall(endpoint, 'DELETE');
    },

    async apiCall(endpoint, method, data = null) {
        if (!this.state.token) {
            this.logout();
            throw new Error("No active session");
        }

        const options = {
            method,
            headers: {
                'Authorization': `Bearer ${this.state.token}`,
                'Content-Type': 'application/json'
            }
        };

        if (data) {
            options.body = JSON.stringify(data);
        }

        try {
            const response = await fetch(endpoint, options);
            
            if (response.status === 401) {
                this.logout();
                throw new Error("Session expired");
            }
            
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || `API Error: ${response.status}`);
            }

            // HTTP 204 No Content
            if (response.status === 204) {
                return null;
            }

            return await response.json();
        } catch (error) {
            console.error(`API Call failed (${method} ${endpoint}):`, error);
            if (method !== 'GET') {
                this.showToast('Request Failed', error.message, 'error');
            }
            throw error;
        }
    },

    // ── Global Polling (Alarms/Telemetry) ──────────────────────────────────

    startPolling() {
        // Poll for alarms initially, then every 30s
        this.pollAlarms();
        this.pollInterval = setInterval(() => this.pollAlarms(), 30000);
    },

    stopPolling() {
        if (this.pollInterval) clearInterval(this.pollInterval);
    },

    async pollAlarms() {
        try {
            const alarms = await this.apiGet('/api/v1/telemetry/alarms?status=active');
            this.state.alarms = alarms;
            
            const criticalCount = alarms.filter(a => a.severity >= 4).length; // Major/Critical
            
            if (criticalCount > 0) {
                this.dom.alarmBadge.textContent = criticalCount;
                this.dom.alarmBadge.style.display = 'block';
            } else {
                this.dom.alarmBadge.style.display = 'none';
            }
        } catch (err) {
            // Silently fail polling
        }
    },

    // ── UI Utilities ─────────────────────────────────────────────────────────

    showToast(title, message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        const iconMap = {
            'success': 'check_circle',
            'warning': 'warning',
            'error': 'error',
            'info': 'info'
        };

        toast.innerHTML = `
            <span class="material-icons-outlined">${iconMap[type]}</span>
            <div class="toast-content">
                <div class="toast-title">${title}</div>
                <div class="toast-message">${message}</div>
            </div>
            <button class="btn-icon" onclick="this.parentElement.remove()">
                <span class="material-icons-outlined">close</span>
            </button>
        `;

        this.dom.toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    },

    showModal(title, contentHtml, footerHtml = '') {
        document.getElementById('modal-title').textContent = title;
        document.getElementById('modal-body').innerHTML = contentHtml;
        
        const footer = document.getElementById('modal-footer');
        if (footerHtml) {
            footer.innerHTML = footerHtml;
            footer.style.display = 'flex';
        } else {
            footer.style.display = 'none';
        }

        const overlay = document.getElementById('modal-overlay');
        overlay.classList.remove('hidden');

        document.getElementById('modal-close').onclick = this.closeModal;
    },

    closeModal() {
        document.getElementById('modal-overlay').classList.add('hidden');
    },

    formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    },

    formatDate(isoString) {
        if (!isoString) return '-';
        return new Date(isoString).toLocaleString();
    }
};

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => App.init());
