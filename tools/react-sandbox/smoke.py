"""Real Docker React fixture smoke; never run AI proposals in this CI job."""
import pathlib
import subprocess
import tempfile

def main():
    image=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','orbit-react:ci'],text=True).strip()
    fixtures=[
        'export default function Component({name}:{name:string}) {return <h1>Welcome {name}</h1>}',
        'export default ({name}:{name:string}) => <section><h1>{["Welcome",name].join(" ")}</h1></section>',
    ]
    for lane,source in zip(('A','B'),fixtures):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            root.chmod(0o755)
            (root/'Component.tsx').write_text(source,encoding='utf-8')
            subprocess.run(['docker','run','--rm','--pull','never','--network','none',
                '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
                '--user','65534:65534','--memory','256m','--cpus','1','--pids-limit','64',
                '--tmpfs','/tmp:rw,noexec,nosuid,size=32m',
                '--mount',f'type=bind,src={root},dst=/work,readonly',image],
                check=True,timeout=60)
            print(f'DEV-{lane}: PASS',flush=True)
if __name__=='__main__':main()
