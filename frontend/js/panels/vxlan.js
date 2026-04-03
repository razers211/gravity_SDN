/**
 * VXLAN Management Panel
 * Lists VRFs, Bridge Domains, VNIs and EVPN pairings.
 */

const VxlanPanel = {
    async init() {
        this.container = document.getElementById('panel-vxlan');
        this.renderSkeleton();
    },

    renderSkeleton() {
        this.container.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>Virtual Networks (VXLAN / EVPN)</h3>
                    <div class="header-actions">
                        <button class="btn btn-outline btn-sm"><span class="material-icons-outlined">refresh</span> Refresh</button>
                    </div>
                </div>
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th>Network Name</th>
                                <th>Type</th>
                                <th>VNI</th>
                                <th>RT / RD</th>
                                <th>Endpoints (VTEPs)</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td style="font-weight:600;">Tenant-A-Prod</td>
                                <td><span class="badge badge-neutral">L3 VRF</span></td>
                                <td>20001 <span style="font-size:11px; color:var(--text-muted);">(L3VNI)</span></td>
                                <td style="font-family:monospace; font-size:12px;">65000:101 / 65000:101</td>
                                <td>4 Leaves</td>
                                <td><span class="badge badge-success">Active</span></td>
                            </tr>
                            <tr>
                                <td style="font-weight:600;">Subnet-Web</td>
                                <td><span class="badge badge-neutral">L2 BD</span></td>
                                <td>10001 <span style="font-size:11px; color:var(--text-muted);">(L2VNI)</span></td>
                                <td style="font-family:monospace; font-size:12px;">65000:102 / 65000:102</td>
                                <td>2 Leaves</td>
                                <td><span class="badge badge-success">Active</span></td>
                            </tr>
                            <tr>
                                <td style="font-weight:600;">Subnet-DB</td>
                                <td><span class="badge badge-neutral">L2 BD</span></td>
                                <td>10002 <span style="font-size:11px; color:var(--text-muted);">(L2VNI)</span></td>
                                <td style="font-family:monospace; font-size:12px;">65000:103 / 65000:103</td>
                                <td>2 Leaves</td>
                                <td><span class="badge badge-success">Active</span></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }
};
