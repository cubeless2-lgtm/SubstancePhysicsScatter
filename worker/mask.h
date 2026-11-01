// File Mask only: strict PNG preflight and bounded public zlib callback. Encoder remains untouched.
struct Mask {
    unsigned width=0,height=0;std::vector<uint16_t> pixels;json diagnostic;
    bool active()const{return !pixels.empty();}
    bool black()const{return active()&&std::all_of(pixels.begin(),pixels.end(),[](uint16_t p){return p==0;});}
    uint64_t bytes()const{return uint64_t(pixels.size())*2;}
};
struct MaskFailure:std::runtime_error{json diagnostic;MaskFailure(const std::string& message,json info):std::runtime_error(message),diagnostic(std::move(info)){};};
static uint64_t mask_add(uint64_t a,uint64_t b){if(b>std::numeric_limits<uint64_t>::max()-a)throw std::runtime_error("Mask arithmetic overflow");return a+b;}
static uint64_t mask_mul(uint64_t a,uint64_t b){if(a&&b>std::numeric_limits<uint64_t>::max()/a)throw std::runtime_error("Mask arithmetic overflow");return a*b;}
struct InflateContext {
    size_t expected=0;uint64_t reserved=0,live=0,peak=0,zlive=0,zpeak=0;unsigned calls=0,allocs=0,ends=0;int reason=0;std::string fault;
    bool reserve(size_t n){if(n>BUDGET-live)return false;live+=n;peak=std::max(peak,live);return true;}
    void release(size_t n){live-=n;}
};
struct alignas(std::max_align_t) ZAllocation {size_t bytes;};
static voidpf mask_zalloc(voidpf opaque,uInt count,uInt size) noexcept {
    auto& c=*static_cast<InflateContext*>(opaque);++c.allocs;
    uint64_t payload=uint64_t(count)*size,total=payload+sizeof(ZAllocation);
    if(c.fault=="internal"||total>std::numeric_limits<size_t>::max()||!c.reserve(size_t(total)))return nullptr;
    auto p=static_cast<ZAllocation*>(std::malloc(size_t(total)));if(!p){c.release(size_t(total));return nullptr;}
    p->bytes=size_t(total);c.zlive+=total;c.zpeak=std::max(c.zpeak,c.zlive);return p+1;
}
static void mask_zfree(voidpf opaque,voidpf value) noexcept {if(value){auto& c=*static_cast<InflateContext*>(opaque);auto p=static_cast<ZAllocation*>(value)-1;c.zlive-=p->bytes;c.release(p->bytes);std::free(p);}}
static unsigned mask_inflate(unsigned char** out,size_t* outsize,const unsigned char* input,size_t input_size,const LodePNGDecompressSettings* settings) noexcept {
    auto& c=*static_cast<InflateContext*>(const_cast<void*>(settings->custom_context));++c.calls;
    if(*out!=nullptr||*outsize!=0){c.reason=1;return 1;}
    unsigned char* buffer=nullptr;bool initialized=false;z_stream stream{};unsigned error=1;
    try {
        if(input_size>std::numeric_limits<uInt>::max()||c.expected>std::numeric_limits<uInt>::max()){c.reason=2;return error;}
        if(c.fault=="out"||!c.reserve(c.expected)){c.reason=3;return error;}
        buffer=static_cast<unsigned char*>(std::malloc(c.expected));if(!buffer){c.release(c.expected);c.reason=3;return error;}
        stream.zalloc=mask_zalloc;stream.zfree=mask_zfree;stream.opaque=&c;
        int status=inflateInit_(&stream,ZLIB_VERSION,c.fault=="init"?int(sizeof(stream)-1):int(sizeof(stream)));
        if(status!=Z_OK)c.reason=4;
        else {
            initialized=true;stream.next_in=const_cast<Bytef*>(input);stream.avail_in=uInt(input_size);stream.next_out=buffer;stream.avail_out=uInt(c.expected);
            status=inflate(&stream,Z_FINISH);
            if(status==Z_STREAM_END&&stream.total_out==c.expected&&stream.avail_in==0)error=0;else c.reason=5;
        }
    }catch(...){c.reason=6;}
    if(initialized){inflateEnd(&stream);++c.ends;}
    if(error){if(buffer){std::free(buffer);c.release(c.expected);}return error;}
    *out=buffer;*outsize=c.expected;return 0;
}
static uint32_t mask_u32(const unsigned char* p){return uint32_t(p[0])<<24|uint32_t(p[1])<<16|uint32_t(p[2])<<8|p[3];}
static json mask_stats(const InflateContext& c){return {{"callback_calls",c.calls},{"zalloc_calls",c.allocs},{"inflate_end_calls",c.ends},{"reason",c.reason},{"expected",c.expected},{"peak_work_bytes",c.peak},{"zlib_peak_bytes",c.zpeak},{"zlib_live_bytes",c.zlive},{"callback_live_bytes",c.live-c.reserved}};}
static Mask decode_mask_bytes(const std::string& bytes,uint64_t geometry_work=0,const std::string& fault=""){
    auto fail=[](const char* message){throw std::runtime_error(message);};
    if(bytes.size()>64*MIB||bytes.size()<8||std::memcmp(bytes.data(),"\x89PNG\r\n\x1a\n",8))fail("Mask PNG signature/file budget invalid");
    const auto* raw=reinterpret_cast<const unsigned char*>(bytes.data());size_t offset=8;unsigned w=0,h=0,bits=0;bool ihdr=false,idat=false,idat_done=false,iend=false;uint64_t idat_size=0;
    uint64_t clean_size=8;
    while(offset<bytes.size()){
        if(bytes.size()-offset<12)fail("Truncated Mask PNG chunk");uint32_t length=mask_u32(raw+offset);uint64_t end=mask_add(offset,mask_add(length,12));if(end>bytes.size())fail("Mask PNG chunk length exceeds file");
        const auto* type=raw+offset+4;std::string name(reinterpret_cast<const char*>(type),4);
        for(auto c:name)if(!((c>='A'&&c<='Z')||(c>='a'&&c<='z')))fail("Invalid Mask PNG chunk type");
        if((type[2]&32)!=0)fail("Invalid PNG reserved chunk bit");
        if(lodepng_crc32(type,size_t(length)+4)!=mask_u32(raw+offset+8+length))fail("Mask PNG CRC mismatch");
        if(!ihdr&&name!="IHDR")fail("Mask IHDR must be first");
        if(name=="IHDR"){
            if(ihdr||length!=13)fail("Duplicate/invalid Mask IHDR");ihdr=true;w=mask_u32(raw+offset+8);h=mask_u32(raw+offset+12);bits=raw[offset+16];
            if(!w||!h||w>8192||h>8192||mask_mul(w,h)>16777216||(bits!=8&&bits!=16)||raw[offset+17]!=0||raw[offset+18]!=0||raw[offset+19]!=0||raw[offset+20]!=0)fail("Mask requires non-interlaced grayscale PNG8/16 within bounds");
        }else if(name=="IDAT"){
            if(idat_done)fail("Non-contiguous Mask IDAT");idat=true;idat_size=mask_add(idat_size,length);if(idat_size>64*MIB)fail("Mask IDAT budget exceeded");
        }else{
            if(idat)idat_done=true;
            if(name=="IEND"){if(length||!idat||end!=bytes.size())fail("Invalid Mask IEND/trailing bytes");iend=true;}
            else if(name=="tRNS"||name=="PLTE"||(type[0]&32)==0)fail("Unsupported Mask critical/alpha/palette chunk");
        }
        if(name=="IHDR"||name=="IDAT"||name=="IEND")clean_size=mask_add(clean_size,uint64_t(length)+12);
        offset=size_t(end);if(iend)break;
    }
    if(!iend||!idat)fail("Mask PNG missing IDAT/IEND");
    uint64_t pixels=mask_mul(w,h),raw_size=mask_mul(pixels,bits/8),expected=mask_mul(h,mask_add(mask_mul(w,bits/8),1)),final_size=mask_mul(pixels,2);
    uint64_t reserved=geometry_work;for(uint64_t n:{uint64_t(bytes.size()),clean_size,clean_size,raw_size,final_size})reserved=mask_add(reserved,n);
    if(expected>33562624||final_size>32*MIB||reserved>BUDGET||expected>BUDGET-reserved)fail("Mask decode/work exceeds 512 MiB budget before allocation");
    std::vector<unsigned char> clean;clean.reserve(size_t(clean_size));clean.insert(clean.end(),raw,raw+8);
    for(size_t position=8;position<bytes.size();){uint32_t length=mask_u32(raw+position);std::string name(reinterpret_cast<const char*>(raw+position+4),4);size_t end=position+size_t(length)+12;
        if(name=="IHDR"||name=="IDAT"||name=="IEND")clean.insert(clean.end(),raw+position,raw+end);position=end;}
    InflateContext context;context.expected=size_t(expected);context.reserved=context.live=context.peak=reserved;context.fault=fault;
    lodepng::State state;state.decoder.color_convert=0;state.decoder.read_text_chunks=0;state.decoder.remember_unknown_chunks=0;state.decoder.ignore_crc=0;state.decoder.ignore_critical=0;
    state.decoder.zlibsettings.custom_zlib=mask_inflate;state.decoder.zlibsettings.custom_context=&context;
    unsigned char* decoded=nullptr;unsigned dw=0,dh=0;unsigned error=lodepng_decode(&decoded,&dw,&dh,&state,clean.data(),clean.size());
    // LodePNG owns and frees successful callback scanlines before returning from decode.
    if(context.reason==0&&context.calls)context.release(context.expected);
    if(error){std::free(decoded);throw MaskFailure("Mask decode/inflate failed",mask_stats(context));}
    std::unique_ptr<unsigned char,decltype(&std::free)> decoded_owner(decoded,&std::free);
    Mask result;result.width=w;result.height=h;result.pixels.resize(size_t(pixels));
    for(size_t i=0;i<pixels;i++)result.pixels[i]=bits==8?uint16_t(decoded[i])*257:uint16_t(unsigned(decoded[i*2])<<8|decoded[i*2+1]);
    result.diagnostic=mask_stats(context);result.diagnostic["idat_bytes"]=idat_size;result.diagnostic["sanitized_bytes"]=clean.size();return result;
}
static uint16_t mask_sample(const Mask& m,double x,double y,double width,double depth){
    if(!m.active())return 65535;double u=x/width+.5,v=.5-y/depth;if(!std::isfinite(u)||!std::isfinite(v))throw std::runtime_error("Non-finite mask coordinates");
    if(u<0||u>1||v<0||v>1)return 0;size_t col=std::min(size_t(m.width-1),size_t(std::floor(u*m.width))),row=std::min(size_t(m.height-1),size_t(std::floor(v*m.height)));return m.pixels[row*m.width+col];
}
static bool mask_accept(uint32_t random,uint16_t probability){return uint64_t(random)*65535ull<uint64_t(probability)*4294967296ull;}
static Mask load_mask(const json& request,uint64_t work=0){
    if(!request.contains("scatter_mask")||request.at("scatter_mask").is_null())return {};
    const auto& descriptor=request.at("scatter_mask");fs::path path=fs::u8path(descriptor.at("path").get<std::string>());uint64_t size=file_bytes(path);if(size>64*MIB)throw std::runtime_error("Mask input exceeds 64 MiB");
    if(work>BUDGET||size>BUDGET-work)throw std::runtime_error("Mask read/work exceeds 512 MiB before allocation");
    std::string bytes(size,'\0');std::ifstream stream(extended_path(path),std::ios::binary);stream.read(bytes.data(),std::streamsize(size));
    if(!stream||stream.peek()!=std::char_traits<char>::eof()||file_bytes(path)!=size)throw std::runtime_error("Mask changed during read");
    if(sha256(bytes)!=descriptor.at("content_hash"))throw std::runtime_error("Mask actual-byte SHA mismatch");return decode_mask_bytes(bytes,work);
}
