/**
 * Transformer Attention Layer Visualization
 * 
 * Logic to handle vector operations and dynamic canvas rendering.
 */

class AttentionViz {
    constructor() {
        this.canvas = document.getElementById('viz-canvas');
        this.ctx = this.canvas.getContext('2d');
        this.dimSlider = document.getElementById('dim-slider');
        this.headSlider = document.getElementById('head-slider');
        this.dimDisplay = document.getElementById('dim-value');
        this.headDisplay = document.getElementById('head-value');
        this.headSelector = document.getElementById('head-selector');
        this.stepBtn = document.getElementById('step-btn');
        this.textInput = document.getElementById('dynamic-input');
        this.valueProjectionContainer = document.getElementById('value-projection');
        
        this.d_k = parseInt(this.dimSlider.value);
        this.headsCount = parseInt(this.headSlider.value);
        this.inputText = "The attention mechanism learns contextual relationships.";
        this.textInput.value = this.inputText;
        this.tokens = this.tokenizeText(this.inputText);
        
        this.selectedRow = 0;
        this.activeHeadIdx = 0;
        this.currentStep = 0;
        
        this.steps = [
            { title: "1. Linear Projection", desc: "Input embeddings are projected into Query, Key, and Value spaces using weight matrices.", formula: "Q = XW^Q, K = XW^K, V = XW^V" },
            { title: "2. Scaled Dot-Product", desc: "We compute the similarity between Query and all Key tokens, scaled by the dimension.", formula: "Score = QK^T / sqrt(d_k)" },
            { title: "3. Softmax Activation", desc: "Scores are converted into probabilities (Attention Weights) that sum to 1.", formula: "Weights = softmax(Scores)" },
            { title: "4. Weighted Sum (Values)", desc: "The final output is a weighted combination of the Value vectors.", formula: "Output = Weights * V" }
        ];

        this.setupEventListeners();
        this.resize();
        this.initData();
        this.animate();
        
        window.addEventListener('resize', () => this.resize());
    }

    tokenizeText(text) {
        return text.trim()
            .split(/\s+/)
            .filter(t => t.length > 0)
            .slice(0, 16); // Limit to 16 tokens for visualization clarity
    }

    setupEventListeners() {
        this.textInput.addEventListener('input', (e) => {
            this.inputText = e.target.value;
            this.tokens = this.tokenizeText(this.inputText);
            if (this.tokens.length > 0) {
                this.initData();
            }
        });

        this.dimSlider.addEventListener('input', (e) => {
            this.d_k = parseInt(e.target.value);
            this.dimDisplay.textContent = this.d_k;
            this.initData();
        });

        this.headSlider.addEventListener('input', (e) => {
            this.headsCount = parseInt(e.target.value);
            this.headDisplay.textContent = this.headsCount;
            this.activeHeadIdx = Math.min(this.activeHeadIdx, this.headsCount - 1);
            this.initData();
        });

        document.getElementById('reset-btn').addEventListener('click', () => {
            this.currentStep = 0;
            this.updateStepUI();
            this.initData();
        });

        this.stepBtn.addEventListener('click', () => {
            this.currentStep = (this.currentStep + 1) % this.steps.length;
            this.updateStepUI();
        });

        this.canvas.addEventListener('mousemove', (e) => this.handleMouseMove(e));
    }

    updateStepUI() {
        const step = this.steps[this.currentStep];
        document.getElementById('step-title').textContent = step.title;
        document.getElementById('step-desc').textContent = step.desc;
        document.getElementById('formula-display').textContent = step.formula;
    }

    renderHeadChips() {
        this.headSelector.innerHTML = '';
        for (let i = 0; i < this.headsCount; i++) {
            const chip = document.createElement('div');
            chip.className = `head-chip ${i === this.activeHeadIdx ? 'active' : ''}`;
            chip.textContent = `Head ${i + 1}`;
            chip.onclick = () => {
                this.activeHeadIdx = i;
                this.renderHeadChips();
            };
            this.headSelector.appendChild(chip);
        }
    }

    handleMouseMove(e) {
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        const cellSize = this.getCellSize();
        const { startX, startY } = this.getMatrixOrigin(cellSize);
        
        if (x >= startX && x <= startX + cellSize * this.seqLen &&
            y >= startY && y <= startY + cellSize * this.seqLen) {
            const row = Math.floor((y - startY) / cellSize);
            if (row !== this.selectedRow) {
                this.selectedRow = row;
            }
        }
    }

    resize() {
        const rect = this.canvas.parentElement.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
    }

    initData() {
        this.seqLen = this.tokens.length;
        this.heads = Array.from({ length: this.headsCount }, () => ({
            Q: Array.from({ length: this.seqLen }, () => 
                Array.from({ length: this.d_k }, () => Math.random() * 2 - 1)
            ),
            K: Array.from({ length: this.seqLen }, () => 
                Array.from({ length: this.d_k }, () => Math.random() * 2 - 1)
            ),
            V: Array.from({ length: this.seqLen }, () => 
                Array.from({ length: this.d_k }, () => Math.random() * 2 - 1)
            ),
            weights: [],
            output: []
        }));
        
        this.calculateAllAttention();
        this.renderHeadChips();
        this.updateStepUI();
        this.renderValueOutput();
    }

    calculateAllAttention() {
        this.heads.forEach(head => {
            const scores = Array.from({ length: this.seqLen }, () => new Array(this.seqLen).fill(0));
            for (let i = 0; i < this.seqLen; i++) {
                for (let j = 0; j < this.seqLen; j++) {
                    let dot = 0;
                    for (let k = 0; k < this.d_k; k++) {
                        dot += head.Q[i][k] * head.K[j][k];
                    }
                    scores[i][j] = dot / Math.sqrt(this.d_k);
                }
            }
            head.weights = scores.map(row => {
                // Numerically stable Softmax implementation (Log-Sum-Exp trick)
                const maxVal = Math.max(...row);
                const exp = row.map(v => Math.exp(v - maxVal));
                const sum = exp.reduce((a, b) => a + b, 0);
                return exp.map(v => v / sum);
            });

            // Calculate Weighted Sum of V for the selected row (for visualization)
            // In a real Transformer, this is done for all rows simultaneously: Output = Softmax(QK^T)V
            head.output = Array.from({ length: this.seqLen }, () => {
                const rowOutput = new Array(this.d_k).fill(0);
                for (let i = 0; i < this.seqLen; i++) {
                    const rowWeights = head.weights[i];
                    for (let j = 0; j < this.seqLen; j++) {
                        const w = rowWeights[j];
                        for (let k = 0; k < this.d_k; k++) {
                            rowOutput[k] += w * head.V[j][k];
                        }
                    }
                }
                return rowOutput;
            });
        });
    }

    getCellSize() {
        const padding = 120;
        return Math.min(
            (this.canvas.width - padding * 2) / this.seqLen,
            (this.canvas.height - padding * 2) / this.seqLen
        );
    }

    getMatrixOrigin(cellSize) {
        return {
            startX: (this.canvas.width - cellSize * this.seqLen) / 2,
            startY: (this.canvas.height - cellSize * this.seqLen) / 2
        };
    }

    renderValueOutput() {
        this.valueProjectionContainer.innerHTML = '';
        const i = this.selectedRow;
        const activeHead = this.heads[this.activeHeadIdx];
        const weights = activeHead.weights[i];
        
        this.tokens.forEach((token, idx) => {
            const item = document.createElement('div');
            item.className = 'output-bar-item';
            item.setAttribute('data-label', token);
            
            // Visualization: use weight as height and opacity
            const weight = weights[idx];
            const height = 10 + weight * 90; // 10% to 100% height
            item.style.height = `${height}%`;
            item.style.opacity = 0.3 + weight * 0.7;
            
            if (idx === i) {
                item.style.boxShadow = `0 0 10px ${this.ctx.strokeStyle}`;
            }

            this.valueProjectionContainer.appendChild(item);
        });
    }

    drawMatrix() {
        const cellSize = this.getCellSize();
        const { startX, startY } = this.getMatrixOrigin(cellSize);
        const activeWeights = this.heads[this.activeHeadIdx].weights;

        for (let i = 0; i < this.seqLen; i++) {
            const isSelected = (i === this.selectedRow);
            const tokenLabel = this.tokens[i] || `T${i+1}`;
            
            this.ctx.fillStyle = isSelected ? '#00f2ff' : '#9499c3';
            this.ctx.font = isSelected ? 'bold 12px Inter' : '10px Inter';
            this.ctx.textAlign = 'right';
            this.ctx.fillText(tokenLabel, startX - 15, startY + i * cellSize + cellSize/2 + 4);

            for (let j = 0; j < this.seqLen; j++) {
                const weight = activeWeights[i][j];
                const x = startX + j * cellSize;
                const y = startY + i * cellSize;

                let opacity = 0.05;
                if (this.currentStep >= 2) {
                    opacity = weight * (isSelected ? 3.0 : 0.6);
                } else if (this.currentStep === 1) {
                    opacity = 0.15;
                }

                const hue = (this.activeHeadIdx * 45) % 360;
                this.ctx.fillStyle = isSelected 
                    ? `hsla(${hue + 180}, 100%, 60%, ${opacity})`
                    : `rgba(255, 255, 255, ${opacity * 0.1})`;
                
                this.ctx.fillRect(x + 1, y + 1, cellSize - 2, cellSize - 2);
                
                this.ctx.strokeStyle = isSelected ? `hsla(${hue + 180}, 100%, 60%, 0.4)` : 'rgba(255, 255, 255, 0.05)';
                this.ctx.lineWidth = isSelected ? 2 : 1;
                this.ctx.strokeRect(x, y, cellSize, cellSize);

                if (i === 0) {
                    const keyLabel = this.tokens[j] || `K${j+1}`;
                    this.ctx.save();
                    this.ctx.translate(x + cellSize/2, startY - 15);
                    this.ctx.rotate(-Math.PI / 4);
                    this.ctx.fillStyle = '#9499c3';
                    this.ctx.textAlign = 'left';
                    this.ctx.font = '10px Inter';
                    this.ctx.fillText(keyLabel, 0, 0);
                    this.ctx.restore();
                }
            }
        }

        if (this.currentStep >= 2) {
            this.drawFlow(startX, startY, cellSize, activeWeights);
        }

        // Optimization: Only re-render the value output if the selected row actually changes, 
        // avoiding unnecessary DOM manipulation and re-rendering of the value panel.
        if (this.selectedRow !== this.lastSelectedRow) {
            this.renderValueOutput();
            this.lastSelectedRow = this.selectedRow;
        }
    }

    drawFlow(startX, startY, cellSize, weights) {
        const i = this.selectedRow;
        const qY = startY + i * cellSize + cellSize / 2;
        const qX = startX - 45;

        for (let j = 0; j < this.seqLen; j++) {
            const weight = weights[i][j];
            const kX = startX + j * cellSize + cellSize / 2;
            const kY = startY - 45;

            if (weight > 0.02) {
                this.ctx.beginPath();
                this.ctx.moveTo(qX, qY);
                this.ctx.bezierCurveTo(qX + 80, qY, kX, kY + 80, kX, kY);
                
                const hue = (this.activeHeadIdx * 45) % 360;
                this.ctx.strokeStyle = `hsla(${hue + 180}, 100%, 60%, ${weight * 0.9})`;
                this.ctx.lineWidth = weight * 12;
                this.ctx.lineCap = 'round';
                
                this.ctx.stroke();
            }
        }
    }

    animate() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.drawMatrix();
        requestAnimationFrame(() => this.animate());
    }
}

window.addEventListener('DOMContentLoaded', () => {
    new AttentionViz();
});
