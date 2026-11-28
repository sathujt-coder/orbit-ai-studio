"""Shared fixed approved PRD and scope contract for P6.2 real acceptance and benchmark."""
def approved_fixture():
    doc=dict(problem='Readers need to save and retrieve links securely',goals=['Save and list links'],users=['Readers'],
        scope=['Web link storage and listing in existing projects'],out_of_scope=['Mobile','Sharing','Registration','Project management'],
        assumptions=['Authenticated project membership is provided'],open_questions=[],
        requirements=[
            dict(id='REQ-1',kind='functional',description='Save URL in own project',priority='must',acceptance=['A saved URL is persisted']),
            dict(id='REQ-2',kind='functional',description='List saved links in own project',priority='must',acceptance=['Saved URL appears in list']),
            dict(id='REQ-3',kind='nonfunctional',description='Enforce project isolation',priority='must',acceptance=['Unauthorized cross-project read is denied'])],
        stories=[dict(id='US-1',actor='Reader',goal='Save and retrieve own links securely',benefit='Find links later',requirements=['REQ-1','REQ-2','REQ-3'])])
    policy=dict(forbidden=['register','sign up','create projects'],rules=[
        dict(requirement='REQ-1',kind='implement',evidence=doc['requirements'][0]['description'],matches=[['save','store','persist','saving','storing','persisting','insert'],['url','urls','link','links']]),
        dict(requirement='REQ-1',kind='verify',evidence=doc['requirements'][0]['acceptance'][0],matches=[['save','saved','persist','persisted','saving','persists','storage'],['url','urls','link','links'],['save','saved','persist','saving','storage']]),
        dict(requirement='REQ-2',kind='implement',evidence=doc['requirements'][1]['description'],matches=[['list','display','retrieve','view','listing','retrieval','show','fetch'],['url','urls','link','links']]),
        dict(requirement='REQ-2',kind='verify',evidence=doc['requirements'][1]['acceptance'][0],matches=[['list','listed','listing','display','displayed','retrieve','view','fetch'],['url','urls','link','links'],['list','listed','listing','display','retrieve','view','fetch']]),
        dict(requirement='REQ-3',kind='implement',evidence=doc['requirements'][2]['description'],matches=[['isolation','isolate','authorization','unauthorized','access','deny','restrict','security'],['project','projects']]),
        dict(requirement='REQ-3',kind='verify',evidence=doc['requirements'][2]['acceptance'][0],matches=[['isolation','unauthorized','denied','deny','cannot','restrict','access'],['project','projects']])])
    return doc,policy
