import {getChatGPTUser,chatGPTSignInPath} from './chatgpt-auth';
import Workspace from '@/components/Workspace';
export const dynamic='force-dynamic';
export default async function Home(){const user=await getChatGPTUser();if(!user)return <main className="signin"><img src="/favicon.svg" alt="" width="44" height="44"/><h1>EmberReady</h1><h2>A safer home starts here.</h2><p>A private wildfire preparedness assessment for your Santa Fe home. Bring together aerial imagery, your photos, and a practical plan.</p><a className="button primary" href={chatGPTSignInPath('/')} target="_top">Sign in with ChatGPT</a><p className="muted small">Your home and photos stay private to your account.</p></main>;return <Workspace displayName={user.displayName}/>;}
