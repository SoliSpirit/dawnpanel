class SecurityHeaders:
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        if request.META.get('REMOTE_ADDR') in ['127.0.0.1','::1']:
            import ipaddress
            value=request.META.get('HTTP_X_REAL_IP','')
            try: request.META['REMOTE_ADDR']=str(ipaddress.ip_address(value))
            except ValueError: pass
        r=self.get_response(request)
        r['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self' https://payment.zarinpal.com https://sandbox.zarinpal.com; base-uri 'self'; object-src 'none'"
        r['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        if request.path.startswith(('/account/','/manage/','/login/','/staff/')):
            r['Cache-Control']='no-store, private';r['X-Robots-Tag']='noindex, nofollow'
        return r
