import type { Metadata } from 'next';
import './globals.css';
export const metadata:Metadata={title:'EmberReady — Your home, better prepared',description:'A private wildfire preparedness assessment for Santa Fe homeowners.',icons:{icon:'/favicon.svg'}};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>;}
