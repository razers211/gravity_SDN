const PathsPanel = {
    async init() {
        document.getElementById('panel-paths').innerHTML = `
            <div class="card">
                <div class="card-header"><h3>End-to-End Path Computation</h3></div>
                <div class="card-body">
                    <div class="form-row">
                        <div class="form-group"><label>Source IP</label><input type="text" placeholder="10.10.1.5"></div>
                        <div class="form-group"><label>Destination IP</label><input type="text" placeholder="10.10.2.20"></div>
                        <div class="form-group"><label>&nbsp;</label><button class="btn btn-primary">Trace Path</button></div>
                    </div>
                </div>
            </div>
        `;
    }
};
