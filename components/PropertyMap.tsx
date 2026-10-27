'use client';
import {useEffect,useRef,useState} from 'react';
import type {Point,Imagery} from '@/lib/types';
const NAIP='https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer';
export default function PropertyMap({point,outline,onPoint,onOutline,mode,image,meta}:{point:Point;outline:Point[];onPoint?:(p:Point)=>void;onOutline?:(p:Point[])=>void;mode:'pin'|'outline'|'view';image?:string;meta?:Imagery}){
 const [ready,setReady]=useState(false);const el=useRef<HTMLDivElement>(null),map=useRef<any>(null),marker=useRef<any>(null),shape=useRef<any>(null),overlay=useRef<any>(null),handlers=useRef({onPoint,onOutline,mode,outline});handlers.current={onPoint,onOutline,mode,outline};
 useEffect(()=>{let disposed=false;void import('leaflet').then(L=>{if(disposed||!el.current)return;const m=L.map(el.current,{center:[point.lat,point.lng],zoom:16,zoomControl:true,maxZoom:20,minZoom:11});map.current=m;
 const Layer:any=L.TileLayer.extend({getTileUrl(c:any){const size=40075016.68557849/2**c.z,x=c.x*size-20037508.342789244,y=20037508.342789244-c.y*size;return NAIP+'/exportImage?'+new URLSearchParams({f:'image',bbox:[x,y-size,x+size,y].join(','),bboxSR:'3857',imageSR:'3857',size:'256,256',format:'jpg',bandIds:'0,1,2'});}});
 new Layer('',{attribution:'USGS / USDA NAIP',maxZoom:20,keepBuffer:1}).addTo(m);marker.current=L.circleMarker([point.lat,point.lng],{radius:8,color:'#fff',fillColor:'#c75430',fillOpacity:1,weight:3}).addTo(m);shape.current=L.polygon([],{color:'#c75430',weight:2,fillOpacity:.12}).addTo(m);
 m.on('click',(e:any)=>{const h=handlers.current;const p={lat:e.latlng.lat,lng:e.latlng.lng};if(h.mode==='outline'&&h.outline.length<40)h.onOutline?.([...h.outline,p]);if(h.mode==='pin')h.onPoint?.(p);});setTimeout(()=>m.invalidateSize(),100);setReady(true);
 });return()=>{disposed=true;map.current?.remove();map.current=null;};},[]);
 useEffect(()=>{if(!map.current)return;marker.current?.setLatLng([point.lat,point.lng,ready]);map.current.panTo([point.lat,point.lng,ready]);},[point.lat,point.lng,ready]);
 useEffect(()=>{shape.current?.setLatLngs(outline.map(p=>[p.lat,p.lng]));},[outline,ready]);
 useEffect(()=>{let disposed=false;if(!image||!meta)return;void import('leaflet').then(L=>{if(disposed||!map.current)return;overlay.current?.remove();overlay.current=L.imageOverlay(image,meta.bounds,{opacity:1}).addTo(map.current);map.current.fitBounds(meta.bounds);shape.current?.bringToFront();marker.current?.bringToFront();});return()=>{disposed=true;};},[image,meta,ready]);
 return <div ref={el} className="property-map" role="region" aria-label="Aerial property map. Click to place a pin or add outline points."/>;
}
