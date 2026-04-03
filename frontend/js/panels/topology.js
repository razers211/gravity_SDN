/**
 * Network Digital Map (Topology Panel)
 * Renders the 3-layer topology graph using Cytoscape.js
 */

const TopologyPanel = {
    cy: null,
    topologyData: null,

    async init() {
        this.container = document.getElementById('panel-topology');
        this.renderSkeleton();
        
        // Wait for next tick so DOM elements are sized
        setTimeout(async () => {
            await this.loadData();
        }, 50);
    },

    renderSkeleton() {
        this.container.innerHTML = `
            <div class="card" style="height: calc(100vh - 120px); display: flex; flex-direction: column;">
                <div class="card-header" style="background:var(--bg-primary);">
                    <div style="display:flex; align-items:center; gap: 16px;">
                        <span class="material-icons-outlined" style="color:var(--primary);">account_tree</span>
                        <h3 style="margin:0;">Network Digital Map</h3>
                    </div>
                    <div class="topology-controls">
                        <select class="filter-select" id="topo-layer-select">
                            <option value="physical">Physical Underlay</option>
                            <option value="logical">Logical Overlay (VXLAN)</option>
                            <option value="application">Application view</option>
                        </select>
                        <button class="btn btn-outline btn-sm" id="topo-fit-btn" title="Fit to Screen">
                            <span class="material-icons-outlined">fit_screen</span>
                        </button>
                        <button class="btn btn-outline btn-sm" id="topo-refresh-btn" title="Refresh Graph">
                            <span class="material-icons-outlined">refresh</span>
                        </button>
                    </div>
                </div>
                <div class="card-body" style="flex:1; padding:0; position:relative;">
                    <div class="topology-legend" style="position:absolute; bottom:16px; left:16px; z-index:10; background:rgba(255,255,255,0.9); padding:8px 12px; border-radius:var(--radius-sm); border:1px solid var(--border);">
                        <div class="topology-legend-item"><div class="topology-legend-dot" style="background:#0066cc;"></div> Spine</div>
                        <div class="topology-legend-item"><div class="topology-legend-dot" style="background:#10b981;"></div> Leaf</div>
                        <div class="topology-legend-item"><div class="topology-legend-dot" style="background:#8b949e;"></div> Server</div>
                        <div class="topology-legend-item"><div class="topology-legend-dot" style="background:#dc2626; border-radius:50%;"></div> Offline / Alarm</div>
                    </div>
                    <div id="cy-container" class="topology-container" style="height:100%; border:none; border-radius:0;">
                        <div class="empty-state" id="topo-loading" style="padding-top:150px;">
                            <span class="material-icons-outlined" style="animation:spin 2s linear infinite;">hourglass_empty</span>
                            <h4>Loading Network Map...</h4>
                        </div>
                    </div>
                </div>
            </div>
            <style>@keyframes spin { 100% { transform: rotate(360deg); } }</style>
        `;

        document.getElementById('topo-layer-select').addEventListener('change', (e) => this.switchLayer(e.target.value));
        document.getElementById('topo-fit-btn').addEventListener('click', () => this.cy && this.cy.fit());
        document.getElementById('topo-refresh-btn').addEventListener('click', () => this.loadData());
    },

    async loadData() {
        document.getElementById('topo-loading').style.display = 'block';
        try {
            // Check if backend implements the topo endpoint, else fallback to local generated data.
            const topoRes = await App.apiGet('/api/v1/topology/tenant').catch(() => null);

            let elements = [];
            if (topoRes) {
                // Parse backend topology response to cytoscape format
                elements = this.parseBackendTopology(topoRes);
            } else {
                // If endpoint not ready, query generic device list to build basic physical view
                const devices = await App.apiGet('/api/v1/devices').catch(() => []);
                elements = this.buildFallbackTopology(devices);
            }

            this.topologyData = elements;
            this.initCytoscape(elements);
        } catch (error) {
            console.error("Topology load failed", error);
            App.showToast("Topology Error", "Could not load network map", "error");
        }
        document.getElementById('topo-loading').style.display = 'none';
    },

    parseBackendTopology(backendData) {
        const elements = [];
        // Map nodes
        (backendData.nodes || []).forEach(n => {
            elements.push({
                data: {
                    id: n.id,
                    label: n.name || n.id,
                    type: n.labels ? n.labels[0].toLowerCase() : 'unknown',
                    status: 'active'
                }
            });
        });
        // Map edges
        (backendData.edges || []).forEach(e => {
            elements.push({
                data: {
                    id: e.id,
                    source: e.source,
                    target: e.target,
                    type: e.type,
                    label: e.type
                }
            });
        });
        return elements;
    },

    buildFallbackTopology(devices) {
        if (!devices || devices.length === 0) {
            return []; // Return empty graph
        }
        const elements = [];
        const spines = devices.filter(d => d.role === 'spine');
        const leaves = devices.filter(d => d.role.includes('leaf'));
        
        devices.forEach(d => {
            elements.push({
                data: {
                    id: d.id,
                    label: d.hostname,
                    type: d.role.includes('spine') ? 'spine' : 'leaf',
                    status: d.status
                }
            });
        });

        // Fully mesh spines to leaves
        spines.forEach(spine => {
            leaves.forEach(leaf => {
                elements.push({
                    data: {
                        id: `link-${spine.id}-${leaf.id}`,
                        source: spine.id,
                        target: leaf.id,
                        type: 'physical'
                    }
                });
            });
        });

        // Add some mock servers connecting to leaves
        let srvId = 1;
        leaves.forEach((leaf, idx) => {
            const numServers = (idx % 2) + 1; // 1 or 2 servers per leaf
            for(let i=0; i<numServers; i++) {
                elements.push({ data: { id: `srv-${srvId}`, label: `server-${srvId}`, type: 'server', status: 'active' }});
                elements.push({ data: { id: `link-srv-${srvId}`, source: leaf.id, target: `srv-${srvId}`, type: 'physical' }});
                srvId++;
            }
        });

        return elements;
    },

    initCytoscape(elements) {
        if (!window.cytoscape) {
            console.error("Cytoscape not loaded");
            return;
        }

        if (this.cy) {
            this.cy.destroy();
        }

        if (elements.length === 0) {
            document.getElementById('cy-container').innerHTML = `
                <div class="empty-state" style="padding-top:150px;">
                    <span class="material-icons-outlined">account_tree</span>
                    <h4>No Topology Data Available</h4>
                    <p>Register devices to build the network map.</p>
                </div>
            `;
            return;
        }

        this.cy = window.cytoscape({
            container: document.getElementById('cy-container'),
            elements: elements,
            style: [
                {
                    selector: 'node',
                    style: {
                        'label': 'data(label)',
                        'text-valign': 'bottom',
                        'text-halign': 'center',
                        'text-margin-y': 6,
                        'font-size': '11px',
                        'font-family': 'Inter, sans-serif',
                        'background-color': '#8b949e', // Default
                        'color': '#1f2937',
                        'width': 35,
                        'height': 35,
                        'border-width': 2,
                        'border-color': '#fff'
                    }
                },
                // Role Specific Node Styles
                {
                    selector: 'node[type="spine"], node[type="super-spine"]',
                    style: {
                        'background-color': '#0066cc',
                        'shape': 'round-rectangle',
                        'width': 50, 'height': 30
                    }
                },
                {
                    selector: 'node[type="leaf"], node[type="border-leaf"], node[type="service-leaf"]',
                    style: {
                        'background-color': '#10b981',
                        'shape': 'round-rectangle',
                        'width': 45, 'height': 25
                    }
                },
                {
                    selector: 'node[type="server"]',
                    style: {
                        'background-color': '#4b5563',
                        'shape': 'ellipse',
                        'width': 20, 'height': 20
                    }
                },
                // Status Specific Overrides
                {
                    selector: 'node[status="offline"], node[status="critical"]',
                    style: {
                        'background-color': '#dc2626',
                        'border-color': '#f87171',
                        'border-width': 3
                    }
                },
                // Edges
                {
                    selector: 'edge',
                    style: {
                        'width': 2,
                        'line-color': '#d1d5db',
                        'curve-style': 'bezier',
                        'target-arrow-shape': 'none'
                    }
                },
                {
                    selector: 'edge[type="overlay"], edge[type="vxlan"]',
                    style: {
                        'line-style': 'dashed',
                        'line-color': '#8b5cf6',
                        'width': 3
                    }
                }
            ],
            layout: {
                name: 'dagre', // Requires pure dagre, standard for hierarchical networking
                rankDir: 'TB',
                nodeSep: 60,
                rankSep: 100
            },
            wheelSensitivity: 0.2
        });

        this.cy.on('tap', 'node', (evt) => {
            const node = evt.target;
            App.showToast('Node Selected', `Hostname: ${node.data('label')} | Type: ${node.data('type')}`, 'info');
        });
    },

    switchLayer(layer) {
        if (!this.cy) return;
        
        // Very basic mock filtering. In reality, you'd fetch different endpoints 
        // depending on layer, or filter the graph.
        this.cy.elements().removeClass('hidden');

        if (layer === 'logical') {
            // Hide physical servers and links, show VXLAN tunnels
            this.cy.nodes('[type="server"]').addClass('hidden');
            this.cy.edges('[type="physical"]').addClass('hidden');
        } else if (layer === 'application') {
            // Hide spine/leaf, show servers/vms
            this.cy.nodes('[type="spine"], [type="leaf"]').addClass('hidden');
        } else {
            // Physical - show all but logical overlays
            this.cy.edges('[type="overlay"]').addClass('hidden');
        }

        this.cy.style().update(); // Force refresh
    }
};
