/**
 * Resource Manager Panel
 * IPAM, VNI, and RT/RD Allocations
 */

const ResourcesPanel = {
    async init() {
        this.container = document.getElementById('panel-resources');
        this.renderSkeleton();
    },

    renderSkeleton() {
        this.container.innerHTML = `
            <div class="tabs">
                <div class="tab active" onclick="ResourcesPanel.switchTab('ipam', this)">IPAM Pools</div>
                <div class="tab" onclick="ResourcesPanel.switchTab('vni', this)">VNI Pools</div>
                <div class="tab" onclick="ResourcesPanel.switchTab('rt', this)">Route Targets</div>
            </div>

            <div id="tab-content">
                <!-- IPAM View -->
                <div class="card" id="view-ipam">
                    <div class="card-header">
                        <h3>IP Address Management</h3>
                        <button class="btn btn-primary btn-sm"><span class="material-icons-outlined">add</span> Create Pool</button>
                    </div>
                    <div class="table-wrapper">
                        <table>
                            <thead>
                                <tr>
                                    <th>Pool Name</th>
                                    <th>CIDR</th>
                                    <th>Gateway</th>
                                    <th>Utilization</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td style="font-weight:500;">Fabric-Underlay</td>
                                    <td>10.0.0.0/16</td>
                                    <td>-</td>
                                    <td>
                                        <div class="utilization-cell">
                                            <div class="progress-bar"><div class="progress-bar-fill blue" style="width:12%"></div></div>
                                            <span>12%</span>
                                        </div>
                                    </td>
                                    <td><button class="btn-text">View</button></td>
                                </tr>
                                <tr>
                                    <td style="font-weight:500;">Tenant-A-VPCs</td>
                                    <td>10.10.0.0/16</td>
                                    <td>-</td>
                                    <td>
                                        <div class="utilization-cell">
                                            <div class="progress-bar"><div class="progress-bar-fill green" style="width:5%"></div></div>
                                            <span>5%</span>
                                        </div>
                                    </td>
                                    <td><button class="btn-text">View</button></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- VNI View -->
                <div class="card hidden" id="view-vni">
                    <div class="card-header">
                        <h3>VXLAN Network Identifiers (VNI)</h3>
                    </div>
                    <div class="table-wrapper">
                        <table>
                            <thead>
                                <tr>
                                    <th>VNI Type</th>
                                    <th>Range Start</th>
                                    <th>Range End</th>
                                    <th>Total Capacity</th>
                                    <th>Allocated</th>
                                    <th>Utilization</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td style="font-weight:500;">L2 VNI (Bridge Domains)</td>
                                    <td>10,000</td>
                                    <td>20,000</td>
                                    <td>10,001</td>
                                    <td>42</td>
                                    <td>
                                        <div class="utilization-cell">
                                            <div class="progress-bar"><div class="progress-bar-fill green" style="width:0.4%"></div></div>
                                            <span>0.4%</span>
                                        </div>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="font-weight:500;">L3 VNI (VRFs)</td>
                                    <td>20,001</td>
                                    <td>25,000</td>
                                    <td>5,000</td>
                                    <td>8</td>
                                    <td>
                                        <div class="utilization-cell">
                                            <div class="progress-bar"><div class="progress-bar-fill green" style="width:0.1%"></div></div>
                                            <span>0.1%</span>
                                        </div>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- RT View -->
                <div class="card hidden" id="view-rt">
                    <div class="card-header">
                        <h3>Route Targets / Distinguishers</h3>
                    </div>
                    <div class="table-wrapper">
                        <table>
                            <thead>
                                <tr>
                                    <th>Type</th>
                                    <th>Format</th>
                                    <th>Assigned To</th>
                                    <th>Value</th>
                                    <th>Allocated At</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><span class="badge badge-neutral">RT</span> Include/Export</td>
                                    <td>Type 0 (ASN:NN)</td>
                                    <td>VRF: Tenant-A-Prod</td>
                                    <td style="font-family:monospace;">65000:101</td>
                                    <td>${App.formatDate(new Date())}</td>
                                </tr>
                                <tr>
                                    <td><span class="badge badge-info">RD</span> Router Distinguisher</td>
                                    <td>Type 0 (ASN:NN)</td>
                                    <td>VRF: Tenant-A-Prod</td>
                                    <td style="font-family:monospace;">65000:101</td>
                                    <td>${App.formatDate(new Date())}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
    },

    switchTab(tabId, el) {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        el.classList.add('active');

        document.getElementById('view-ipam').classList.add('hidden');
        document.getElementById('view-vni').classList.add('hidden');
        document.getElementById('view-rt').classList.add('hidden');

        document.getElementById(`view-${tabId}`).classList.remove('hidden');
    }
};
