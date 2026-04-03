const UsersPanel = {
    async init() {
        document.getElementById('panel-users').innerHTML = `
            <div class="card">
                <div class="card-header"><h3>User Management (RBAC)</h3></div>
                <div class="table-wrapper">
                    <table>
                        <thead><tr><th>Username</th><th>Role</th><th>Status</th></tr></thead>
                        <tbody><tr><td>admin</td><td><span class="badge badge-success">Administrator</span></td><td>Active</td></tr></tbody>
                    </table>
                </div>
            </div>
        `;
    }
};
