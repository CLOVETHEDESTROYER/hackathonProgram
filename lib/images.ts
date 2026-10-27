// Re-encoded browser uploads are checked again on the server. Drop all optional
// JPEG metadata (including EXIF GPS), rather than trusting an upload flag.
export function sanitizeJpeg(input:Uint8Array):Uint8Array {
  if(input.length<4 || input[0]!==255 || input[1]!==216) throw new Error('Upload a JPEG image. Your browser converts supported photos automatically.');
  const chunks:Uint8Array[]=[input.slice(0,2)]; let i=2; let foundDimensions=false;let foundScan=false;
  while(i<input.length){
    if(input[i]!==255) throw new Error('Invalid JPEG structure.');
    const start=i; while(input[i]===255) i++; const marker=input[i++];
    if(marker===217){chunks.push(input.slice(start,i));break;}
    if(marker===218){
      if(!foundDimensions)throw new Error('Missing image dimensions.');
      const length=(input[i]<<8)|input[i+1];if(length<2||i+length>input.length)throw new Error('Incomplete image scan.');
      i+=length;foundScan=true;
      while(i<input.length){if(input[i]!==255){i++;continue;}const next=input[i+1];if(next===0||next>=208&&next<=215){i+=2;continue;}break;}
      chunks.push(input.slice(start,i));continue;
    }
    if(marker===0 || marker===216 || marker>=208&&marker<=215) throw new Error('Invalid JPEG marker.');
    const length=(input[i]<<8)|input[i+1]; if(length<2||i+length>input.length) throw new Error('Incomplete image.');
    if([192,193,194].includes(marker)){const h=(input[i+3]<<8)|input[i+4],w=(input[i+5]<<8)|input[i+6];if(!h||!w||h>1600||w>1600)throw new Error('Image must be no larger than 1600 pixels per side.'); foundDimensions=true;}
    if(!(marker>=224&&marker<=239)&&marker!==254)chunks.push(input.slice(start,i+length));
    i+=length;
  }
  if(!foundDimensions || !foundScan || input[input.length-2]!==255||input[input.length-1]!==217)throw new Error('Incomplete JPEG image.');
  const out=new Uint8Array(chunks.reduce((n,c)=>n+c.length,0));let at=0;for(const c of chunks){out.set(c,at);at+=c.length;}return out;
}
