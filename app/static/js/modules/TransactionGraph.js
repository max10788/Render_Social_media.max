// /static/js/modules/TransactionGraph.js
export class TransactionGraph {
    constructor(containerSelector, options = {}) {
        this.container = document.querySelector(containerSelector);
        if (!this.container) {
            console.error(`Container "${containerSelector}" nicht gefunden`);
            return;
        }
        this.width = options.width || 800;
        this.height = options.height || 600;
        this.tooltip = d3.select("body").append("div").attr("class", "transaction-tooltip").style("opacity", 0);
    }

   _init() {
        // Leere vorherigen Inhalt
        this.container.innerHTML = "";
    
        // SVG erstellen
        this.svg = d3.select(this.container)
            .append("svg")
            .attr("width", this.width)
            .attr("height", this.height)
            .attr("class", "transaction-graph");
    
        // Zoom-Gruppe hinzufügen
        this.zoomGroup = this.svg.append("g").attr("class", "zoom-group");
    
        // Tooltip erstellen
        this.tooltip = d3.select(this.container)
            .append("div")
            .attr("class", "transaction-tooltip")
            .style("opacity", 0);
    
        // Gruppen für Elemente (innerhalb der Zoom-Gruppe)
        this.linksGroup = this.zoomGroup.append("g").attr("class", "links");
        this.nodesGroup = this.zoomGroup.append("g").attr("class", "nodes");
        this.labelsGroup = this.zoomGroup.append("g").attr("class", "labels");
    
        // Zoom-Verhalten initialisieren
        this.zoomBehavior = d3.zoom()
            .scaleExtent([0.1, 4]) // Min-/Max-Zoom
            .on("zoom", (event) => {
                this.zoomGroup.attr("transform", event.transform);
            });
    
        this.svg.call(this.zoomBehavior);
    }

    update(data) {
        console.log("Empfangene Rohdaten:", data);
        const graphData = this._processData(data);
        console.log("Verarbeitete Graphdaten:", graphData);
    
        if (!graphData.nodes.length || !graphData.links.length) {
            console.warn("Keine Knoten oder Links zum Zeichnen gefunden!");
            this.container.innerHTML = "<div style='padding: 20px; color: #9ca3af;'>Keine darstellbaren Transaktionen gefunden.</div>";
            return;
        }
    
        this.nodes = graphData.nodes;
        this.links = graphData.links;
    
        // Simulation initialisieren
        this.simulation = d3.forceSimulation(this.nodes)
            .force("link", d3.forceLink(this.links).id(d => d.id).distance(150))
            .force("charge", d3.forceManyBody().strength(-400))
            .force("center", d3.forceCenter(this.width / 2, this.height / 2));

        // Links rendern
        this.linkElements = this.linksGroup.selectAll("line")
            .data(this.links)
            .join("line")
            .attr("class", d => `link ${d.highlighted ? 'highlighted' : ''}`)
            .style("stroke-width", d => Math.max(1, Math.log(d.value + 1)));

        // Nodes rendern
        this.nodeElements = this.nodesGroup.selectAll("circle")
            .data(this.nodes)
            .join("circle")
            .attr("r", this.nodeRadius)
            .attr("class", d => {
                let cls = "node";
                if (d.type === "wallet") cls += " wallet";
                if (d.start) cls += " start";
                if (d.end) cls += " end";
                if (d.highValue) cls += " high-value";
                else if (d.mediumValue) cls += " medium-value";
                else cls += " low-value";
                return cls;
            })
            .call(this._drag(this.simulation))
            .on("mouseover", (event, d) => this._showTooltip(event, d))
            .on("mouseout", () => this._hideTooltip())
            .on("click", (event, d) => this._dispatchNodeClick(event, d));

        // Labels rendern
        this.labelElements = this.labelsGroup.selectAll("text")
            .data(this.nodes)
            .join("text")
            .attr("class", "node-label")
            .text(d => this._shortenAddress(d.id))
            .attr("dy", 4);

        // Tick-Handler
        this.simulation.on("tick", () => {
            this.linkElements
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);

            this.nodeElements
                .attr("cx", d => d.x)
                .attr("cy", d => d.y);

            this.labelElements
                .attr("x", d => d.x)
                .attr("y", d => d.y);
        });
    }

    _processData(transactions) {
        const nodesMap = new Map();
        const links = [];
        
        transactions.forEach(tx => {
            const fromWallet = tx.from_wallet;
            const changes = tx.balance_changes || [];
            
            if (!nodesMap.has(fromWallet)) {
                nodesMap.set(fromWallet, {
                    id: fromWallet,
                    type: "wallet",
                    start: true,
                    label: "Quelle",
                    transaction: tx,
                    balance_changes: changes
                });
            }
            
            changes.forEach(change => {
                const account = change.account;
                const amount = Math.abs(change.change / 1e9);
                
                // Entferne die Prüfung auf signifikante Beträge
                if (!nodesMap.has(account)) {
                    nodesMap.set(account, {
                        id: account,
                        type: "wallet",
                        label: `±${amount.toFixed(4)} SOL`,
                        transaction: tx,
                        balance_changes: changes
                    });
                }
                
                links.push({
                    source: fromWallet,
                    target: account,
                    value: amount,
                    highlighted: change.change < 0
                });
            });
        });
        
        return {
            nodes: Array.from(nodesMap.values()),
            links
        };
    }

    _drag(simulation) {
        return d3.drag()
            .on("start", (event, d) => {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
            })
            .on("drag", (event, d) => {
                d.fx = event.x;
                d.fy = event.y;
            })
            .on("end", (event, d) => {
                if (!event.active) simulation.alphaTarget(0);
                d.fx = null;
                d.fy = null;
            });
    }

    _showTooltip(event, d) {
        const tx = d.transaction || {};
        const meta = tx.meta || {};
        const account_keys = tx.transaction?.message?.accountKeys || [];
        const balance_changes = d.balance_changes || [];

        const fee = meta.fee ? (meta.fee / 1e9).toFixed(6) + " SOL" : "N/A";
        const block_time = tx.block_time ? new Date(tx.block_time * 1000).toLocaleString() : "N/A";

        let content = `
            <div class="tooltip-header">Konto: ${this._shortenAddress(d.id)}</div>
            <div class="tooltip-body">
                <div class="timestamp-label">Transaktions-Hash: ${tx.signature || "N/A"}</div>
                <div class="timestamp-label">Datum: ${block_time}</div>
                <div class="amount-label">Gebühr: ${fee}</div>
                <div><strong>Beteiligte Accounts:</strong> (${account_keys.length})</div>
                <ul>${account_keys.slice(0, 5).map((acc, i) => `<li title="${acc}">${acc.substring(0, 10)}...</li>`).join("")}</ul>
                <div><strong>Balance-Änderungen:</strong></div>
                <ul>${balance_changes.map(change => {
                    const sign = change.change > 0 ? "+" : "";
                    return `<li>${change.account.substring(0, 10)}...: <span class="${sign.startsWith('+') ? 'amount-label' : 'error'}">${sign}${change.change.toFixed(4)} SOL</span></li>`;
                }).join("")}</ul>
            </div>
        `;

        this.tooltip.html(content)
            .style("left", `${event.pageX + 10}px`)
            .style("top", `${event.pageY - 28}px`)
            .style("opacity", 0.9);
    }


    _hideTooltip() {
        this.tooltip.transition().duration(500).style("opacity", 0);
    }

    _shortenAddress(address) {
        return address.length > 10 ? address.slice(0, 6) + "..." + address.slice(-4) : address;
    }

    _dispatchNodeClick(event, node) {
        const customEvent = new CustomEvent('nodeClick', {
            detail: { node },
            bubbles: true,
            cancelable: true
        });
        this.container.dispatchEvent(customEvent);
    }
}
