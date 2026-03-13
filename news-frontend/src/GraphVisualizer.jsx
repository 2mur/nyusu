import React, { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';

const GraphVisualizer = ({ graph }) => {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!containerRef.current) return;
    const resizeObserver = new ResizeObserver((entries) => {
      for (let entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  useEffect(() => {
    const validNodeIds = new Set(graph.nodes.map(n => n.id));

    const validEdges = graph.edges.filter(edge => 
      validNodeIds.has(edge.source) && validNodeIds.has(edge.target)
    );

    if (validEdges.length < graph.edges.length) {
      console.warn("GraphVisualizer: Removed invalid edges that pointed to missing nodes.");
    }

    if (!svgRef.current || !graph.nodes.length || dimensions.width === 0) return;

    const { width, height } = dimensions;
    const padding = 15; // Padding to keep nodes slightly away from the exact edge

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const simulation = d3.forceSimulation(graph.nodes)
      .force("link", d3.forceLink(validEdges).id((d) => d.id).distance(80))
      .force("charge", d3.forceManyBody().strength(-200))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(40));

    svg.append("defs").append("marker")
      .attr("id", "arrowhead")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 20)
      .attr("refY", 0)
      .attr("orient", "auto")
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", "rgba(255,255,255,0.2)");

    const link = svg.append("g")
      .selectAll("line")
      .data(validEdges)
      .join("line")
      .attr("stroke", "rgba(255,255,255,0.1)")
      .attr("stroke-width", 1)
      .attr("marker-end", "url(#arrowhead)");

    const linkText = svg.append("g")
      .selectAll("text")
      .data(validEdges)
      .join("text")
      .attr("font-size", "9px")
      .attr("font-family", "monospace")
      .attr("fill", "rgba(255,255,255,0.4)")
      .attr("text-anchor", "middle")
      .text((d) => d.relation);

    const node = svg.append("g")
      .selectAll("g")
      .data(graph.nodes)
      .join("g")
      .call(d3.drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended));

    node.append("circle")
      .attr("r", 6)
      .attr("fill", "#f88") 
      .attr("stroke", "#1a1a1a")
      .attr("stroke-width", 2);

    node.append("text")
      .attr("dx", 10)
      .attr("dy", 4)
      .attr("font-size", "10px")
      .attr("font-weight", "500")
      .attr("fill", "rgba(255,255,255,0.8)")
      .text((d) => d.id);

    simulation.on("tick", () => {
      // Bounding box logic: restrict d.x and d.y to stay within the container dimensions
      node.attr("transform", (d) => {
        d.x = Math.max(padding, Math.min(width - padding, d.x));
        d.y = Math.max(padding, Math.min(height - padding, d.y));
        return `translate(${d.x},${d.y})`;
      });

      link.attr("x1", (d) => d.source.x)
          .attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x)
          .attr("y2", (d) => d.target.y);
          
      linkText.attr("x", (d) => (d.source.x + d.target.x) / 2)
              .attr("y", (d) => (d.source.y + d.target.y) / 2 - 5);
    });

    function dragstarted(event) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }

    function dragged(event) {
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }

    function dragended(event) {
      if (!event.active) simulation.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }

    return () => simulation.stop();
  }, [graph, dimensions]);

  return (
    <div ref={containerRef} className="visual-container graph-wrapper">
      <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
};

export default GraphVisualizer;