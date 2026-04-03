/**
 * Service Provisioning Panel
 * Intent-based networking wizard (Tenant -> VPC -> Subnet -> Policy)
 */

const ProvisioningPanel = {
    async init() {
        this.container = document.getElementById('panel-provisioning');
        this.renderSkeleton();
    },

    renderSkeleton() {
        this.container.innerHTML = `
            <div class="card" style="max-width:900px; margin:0 auto;">
                <div class="card-header">
                    <h3>Service Provisioning Intent</h3>
                </div>
                
                <div class="card-body">
                    <div class="wizard-steps">
                        <div class="wizard-step active" id="step-1-nav">
                            <div class="step-number">1</div>
                            <div class="step-label">Tenant</div>
                        </div>
                        <div class="wizard-step" id="step-2-nav">
                            <div class="step-number">2</div>
                            <div class="step-label">VPC (VRF)</div>
                        </div>
                        <div class="wizard-step" id="step-3-nav">
                            <div class="step-number">3</div>
                            <div class="step-label">Subnets (L2/L3)</div>
                        </div>
                        <div class="wizard-step" id="step-4-nav">
                            <div class="step-number">4</div>
                            <div class="step-label">Deploy</div>
                        </div>
                    </div>

                    <form id="intent-wizard-form" autocomplete="off">
                        <!-- Step 1: Tenant -->
                        <div id="step-1-content" class="wizard-content">
                            <h4 style="margin-bottom:16px;">Define Tenant</h4>
                            <div class="form-group">
                                <label>Tenant Name</label>
                                <input type="text" id="prov-tenant-name" required placeholder="e.g. Finance-Dept">
                            </div>
                        </div>

                        <!-- Step 2: VPC -->
                        <div id="step-2-content" class="wizard-content hidden">
                            <h4 style="margin-bottom:16px;">Define VPC (Mapped to VRF)</h4>
                            <div class="form-group">
                                <label>VPC Name</label>
                                <input type="text" id="prov-vpc-name" placeholder="e.g. Prod-VPC" required>
                            </div>
                            <div class="form-group">
                                <label>Auto-Allocate RT/RD?</label>
                                <select id="prov-vpc-rt">
                                    <option value="auto">Yes (Resource Manager)</option>
                                    <option value="manual">No (Manual Input)</option>
                                </select>
                            </div>
                        </div>

                        <!-- Step 3: Subnets -->
                        <div id="step-3-content" class="wizard-content hidden">
                            <h4 style="margin-bottom:16px;">Define Subnets</h4>
                            <div id="subnet-list" style="margin-bottom:16px;">
                                <div class="subnet-row form-row" style="align-items:flex-end;">
                                    <div class="form-group"><label>Subnet Name</label><input type="text" class="sub-name" placeholder="Web-Tier" required></div>
                                    <div class="form-group"><label>CIDR</label><input type="text" class="sub-cidr" placeholder="10.10.1.0/24" required></div>
                                    <div class="form-group"><label>Gateway</label><input type="text" class="sub-gw" placeholder="10.10.1.1"></div>
                                </div>
                            </div>
                            <button type="button" class="btn btn-outline btn-sm" onclick="ProvisioningPanel.addSubnetRow()">+ Add Subnet</button>
                        </div>

                        <!-- Step 4: Preview -->
                        <div id="step-4-content" class="wizard-content hidden">
                            <h4 style="margin-bottom:16px;">Preview & Verify</h4>
                            <p style="font-size:13px; color:var(--text-secondary); margin-bottom:16px;">
                                The Intent Verification Engine will validate this payload for routing loops, IP conflicts, and VNI uniqueness before translating it to NETCONF.<br><br>
                                Click <strong>Verify & Deploy</strong> to initiate the ACID multi-device transaction.
                            </p>
                            <div class="code-editor" id="intent-preview"></div>
                        </div>

                    </form>
                </div>
                <div class="card-footer">
                    <button class="btn btn-outline hidden" id="wiz-prev" onclick="ProvisioningPanel.prevStep()">Previous</button>
                    <button class="btn btn-primary" id="wiz-next" onclick="ProvisioningPanel.nextStep()">Next</button>
                    <button class="btn btn-success hidden" id="wiz-deploy" onclick="ProvisioningPanel.deployIntent()">Verify & Deploy</button>
                </div>
            </div>
        `;
        this.currentStep = 1;
    },

    addSubnetRow() {
        const div = document.createElement('div');
        div.className = 'subnet-row form-row';
        div.style.alignItems = 'flex-end';
        div.style.marginTop = '12px';
        div.innerHTML = `
            <div class="form-group"><label>Subnet Name</label><input type="text" class="sub-name" placeholder="App-Tier" required></div>
            <div class="form-group"><label>CIDR</label><input type="text" class="sub-cidr" placeholder="10.10.2.0/24" required></div>
            <div class="form-group"><label>Gateway</label><input type="text" class="sub-gw" placeholder="10.10.2.1"></div>
            <button type="button" class="btn-icon" style="margin-bottom:16px; color:var(--danger);" onclick="this.parentElement.remove()"><span class="material-icons-outlined">delete</span></button>
        `;
        document.getElementById('subnet-list').appendChild(div);
    },

    prevStep() {
        if (this.currentStep > 1) {
            this.currentStep--;
            this.updateView();
        }
    },

    nextStep() {
        // Very basic frontend validation
        const currentContent = document.getElementById(`step-${this.currentStep}-content`);
        const inputs = currentContent.querySelectorAll('input[required]');
        for(let input of inputs) {
            if(!input.value) {
                App.showToast("Validation Error", "Please fill all required fields", "warning");
                return;
            }
        }

        if (this.currentStep < 4) {
            this.currentStep++;
            if (this.currentStep === 4) {
                this.generatePayload();
            }
            this.updateView();
        }
    },

    updateView() {
        // Update nav steps
        for(let i=1; i<=4; i++) {
            const navUrl = document.getElementById(`step-${i}-nav`);
            if (i < this.currentStep) {
                navUrl.className = 'wizard-step completed';
            } else if (i === this.currentStep) {
                navUrl.className = 'wizard-step active';
            } else {
                navUrl.className = 'wizard-step';
            }

            const content = document.getElementById(`step-${i}-content`);
            if (i === this.currentStep) {
                content.classList.remove('hidden');
            } else {
                content.classList.add('hidden');
            }
        }

        // Update buttons
        document.getElementById('wiz-prev').classList.toggle('hidden', this.currentStep === 1);
        document.getElementById('wiz-next').classList.toggle('hidden', this.currentStep === 4);
        document.getElementById('wiz-deploy').classList.toggle('hidden', this.currentStep !== 4);
    },

    generatePayload() {
        const tenant = document.getElementById('prov-tenant-name').value;
        const vpc = document.getElementById('prov-vpc-name').value;
        
        const subnets = [];
        document.querySelectorAll('.subnet-row').forEach(row => {
            subnets.push({
                name: row.querySelector('.sub-name').value,
                cidr: row.querySelector('.sub-cidr').value,
                gateway: row.querySelector('.sub-gw').value || undefined
            });
        });

        this.payload = {
            tenant: { name: tenant },
            vpcs: [
                {
                    name: vpc,
                    subnets: subnets
                }
            ]
        };

        document.getElementById('intent-preview').textContent = JSON.stringify(this.payload, null, 4);
    },

    async deployIntent() {
        document.getElementById('wiz-deploy').disabled = true;
        document.getElementById('wiz-deploy').textContent = 'Validating...';

        try {
            const result = await App.apiPost('/api/v1/intents', this.payload);
            App.showToast("Deployment Started", `Intent ${result.intent_id} submitted successfully.`, "success");
            
            // In reality, we'd navigate to an intent status page or back to dashboard
            setTimeout(() => {
                window.location.hash = '#dashboard';
            }, 1500);

        } catch (error) {
            document.getElementById('wiz-deploy').disabled = false;
            document.getElementById('wiz-deploy').textContent = 'Verify & Deploy';
            App.showToast("Deployment Failed", error.message, "error");
        }
    }
};
