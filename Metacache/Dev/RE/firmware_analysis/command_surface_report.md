# Firmware command-surface scan

Tokens that look like Remote Command Protocol mnemonics, found
in the **Main 1.26.01** firmware string table. Cross-referenced
against V1.02 + V2.00 spec command lists. Tokens with many
false-positive contexts are noise; tokens with few contexts are
high-signal candidates for undocumented commands.

## Known spec commands present in firmware strings

| Token | V1.02 | V2.00 | BCDx36HP | First context |
| --- | --- | --- | --- | --- |
| `GW2` |  | yes |  | `p-GW2/%Qw{` |

## Unknown 3-6 char uppercase tokens (raw firmware strings)

Most are noise (variable names, bitmask labels, file-format
type tags). The interesting ones are 3-letter standalone
tokens that don't decode to anything obvious from English.

| Token | hits | First 3 contexts |
| --- | --- | --- |
| `PX` | 4 | `lEH_]vZ#PX // U7\|PX^ // L r)PX` |
| `A_` | 3 | `u!A_+u // NW[=A_ // A_?mxQ` |
| `DG` | 3 | `FA&DG+ // DG+$s; // DG"U@o` |
| `N4` | 3 | `N4&&lO // "#N4:Qmx // N4:u(j` |
| `NW` | 3 | `OIW$NW // NW[=A_ // F.NW:z` |
| `O0` | 3 | ``$RF.O0 // ~O0:*G // \O0%K\|` |
| `OV` | 3 | `*`bn`OV // ]ew@OV // OV-W;%` |
| `PR` | 3 | `PR?}eBq // nri\|PR // B}PR%4P{e)u` |
| `Q8` | 3 | `0!Q8]= // ^>-Q8]~--t // 8~Q8 p5` |
| `AD` | 2 | `AD{&z)dr // 91`"AD` |
| `AL` | 2 | `.T"t%AL+ // E6L@AL%` |
| `AT` | 2 | `{AT']b // AT'3tq` |
| `AZ` | 2 | `AZ<'Dc // <(;AZ<` |
| `BR` | 2 | `9:BR F // o=.X>]0^BR` |
| `B_` | 2 | `;]B_~v // )9i]B_` |
| `C3` | 2 | `Dl\|{C3 // k`7zhw{C3` |
| `CQ` | 2 | `}CQ[b 5b- // CQ+HB7` |
| `DE` | 2 | `"NOO@F$DE // (n}DE=` |
| `DV` | 2 | `DV,AKP // 48O\|DV` |
| `DY` | 2 | `DY)4cR // jV!^V!b,DY` |
| `EO` | 2 | `)#EO`m // EO!o;c` |
| `ES` | 2 | `3'*i$ES // ES%c&G` |
| `FA` | 2 | `FA&DG+ // )g\FA%` |
| `FH` | 2 | `FH>CGd // Hdh^FH` |
| `FS` | 2 | `*/(FS  // .FS)SF` |
| `G1` | 2 | `y&G1?/( // 4\x-G1` |
| `GA` | 2 | `\GA<+^ // g^eA[GA}` |
| `GM` | 2 | `GM\q$7 // _AG}GM` |
| `GO` | 2 | `$AU'a9;GO // j GO/x` |
| `H1` | 2 | `H1:,(2 // r50#H1` |
| `HA` | 2 | `HA:TJ8+ // HA#o&+` |
| `HW` | 2 | `{>/,w?HW // O:HW\|}` |
| `I0` | 2 | `Vmu)I0 // I0~9@#,Wh` |
| `IB` | 2 | `Xg]IB!Ac // ,$?vt*IB` |
| `IC` | 2 | `#=H+IC // tbU]IC` |
| `JI` | 2 | `0R7{JI // JI]x"mi` |
| `JX` | 2 | `JX}g~1 // JX\nZ!` |
| `KE` | 2 | `)Y~KE, // s~0*KE` |
| `KP` | 2 | `YCxE%KP{+"` // $KP:sJ%` |
| `K_` | 2 | `.K_-\|." // }kr;K&K_` |
| `L1` | 2 | `_\7,L1 // !O }L1` |
| `L4` | 2 | `g*Y;L4 // ;S/L4:` |
| `LI` | 2 | `*LI=}60ELfl // ,LI<42` |
| `LN` | 2 | ``>_/LN // dE[WSU%LN` |
| `LZ` | 2 | `LZ#;9" // KM+LZ!R+:` |
| `ML` | 2 | `C*ML[, //  ML!C,` |
| `NG` | 2 | `ew$NG,< // *&NG>z` |
| `NV` | 2 | `z&NV;X // NV?Rb~` |
| `NX` | 2 | `\NX"DL // `\NX=G` |
| `NXE` | 2 | `NXE]tr // NXE%2\` |
| `O5` | 2 | `O5~NT&w // O5{txU` |
| `OB` | 2 | `#B=5/OB // k<OB<V` |
| `ON` | 2 | `*r\ON%>N //  ON}MYC` |
| `OS` | 2 | `e>/+OS-@ // OS.1.A` |
| `OX` | 2 | `OX{,0Bg // >[K-OX` |
| `QP` | 2 | `QQ.QP+ // QP\|2FE?` |
| `QU` | 2 | `Qx\&QU* // h"\F\|QU` |
| `RU` | 2 | `;u(RU&s // )7d\RU` |
| `S5` | 2 | `S5\34f // y@S5}N_e` |
| `SU` | 2 | `^[SU/* // t>`!+SU` |
| `T2` | 2 | `yFd'T2* // T2(\|Ffg` |
| `TE` | 2 | `TE{s[{<[ // TE%o{o` |
| `TJ` | 2 | `TJ=ch/ // TJ~$HY` |
| `UP` | 2 | `qHm^B=UP // UP$F-j` |
| `UT` | 2 | `&^(=UT{ // Hl"UT>` |
| `V_` | 2 | `yd=)V_ // V_[+6%` |
| `WZ` | 2 | `i:$C"WZ // WZ&>Bi4x` |
| `YO` | 2 | `-o>{+YO // 6+W<YO` |
| `YX` | 2 | `I"YX.m // .\YX#6` |
| `ZE` | 2 | `ZE[ey.% // ZE>VIh` |
| `ZN` | 2 | `8*ZN[-xd // ZN^i5/` |
| `ZQ` | 2 | `'p{\|ZQ // ZQ,Ms]wB` |
| `A3` | 1 | `6{r#A3` |
| `AHKQ` | 1 | `@-AHKQ` |
| `AHSK` | 1 | `@g(AHSK` |
| `AI` | 1 | `O-AI!w[2` |
| `AIT` | 1 | `AIT"{q2wO` |
| `AKP` | 1 | `DV,AKP` |
| `AL2` | 1 | `* =AL2` |
| `AP` | 1 | `3{AP =*w/` |
| `AQ` | 1 | `AQ`OM}v` |
| `AS` | 1 | `-$+Q&]AS?d(M!` |
| `AU` | 1 | `$AU'a9;GO` |
| `AVRT` | 1 | `AVRT.9` |
| `AWQ` | 1 | `%\|\AWQ` |
| `A_X` | 1 | `A_X[Wg9e` |
| `B0` | 1 | `B0.d_O]` |
| `B1` | 1 | `2U)B1+` |
| `B2` | 1 | `%B2@.<` |
| `B9` | 1 | `Nc^B9)` |
| `BB` | 1 | `^BB\|O ` |
| `BC` | 1 | `BC<n)V` |
| `BECC` | 1 | `G@BECC` |
| `BF` | 1 | `%6!:BF` |
| `BH` | 1 | `W,V[BH` |
| `BI` | 1 | `}BI{+x` |
| `BL2` | 1 | `K+BL2{Q` |
| `BM` | 1 | `\BM)#P` |
| `BN2J` | 1 | `u}BN2J` |
| `BP` | 1 | `g(BP'J` |
| `BRQ` | 1 | `EA&BRQ` |
| `BV` | 1 | `BV{[16` |
| `BW` | 1 | `BW>}!u` |
| `C10` | 1 | `&9%C10{` |
| `C2` | 1 | `n5c C2=` |
| `C4` | 1 | `p/C4@\M.]%VsQ` |
| `C8LI` | 1 | `y:C8LI#` |
| `CA0` | 1 | `[6}CA0` |
| `CI` | 1 | `H.CI&Eq` |
| `CL` | 1 | `w3K(CL` |
| `CQSPR` | 1 | `CQSPR<O)<` |
| `CT` | 1 | `J>),{CT` |
| `C_` | 1 | `_7B;C_` |
| `D2` | 1 | `lV/D2]tp` |
| `D3` | 1 | `&D3:;T` |
| `D77` | 1 | `8Ux D77` |
| `D85` | 1 | ` wX!D85` |
| `DC` | 1 | `_{ !`DC` |
| `DC4C` | 1 | `@DC4C\` |
| `DC6` | 1 | `$w#DC6` |
| `DD` | 1 | `DD,}Mi&` |
| `DJ` | 1 | `x@DJ)oI` |
| `DL` | 1 | `\NX"DL` |
| `DM` | 1 | `n#j=DM` |
| `DOJ` | 1 | `DOJ@H^E` |
| `DR` | 1 | `Xgf<DR!` |
| `DTQ` | 1 | `DTQ+VS` |
| `DZ` | 1 | `%!"fU]DZ` |
| `DZL` | 1 | `"DZL$kSy` |
| `E0` | 1 | `E0,L>r` |
| `E3` | 1 | `\_Ki""E3` |
| `E5` | 1 | `.E5(s8` |
| `E5I` | 1 | `)E5I>:` |
| `E6L` | 1 | `E6L@AL%` |
| `E6X` | 1 | `"a@E6X'` |
| `E7` | 1 | `E7,=Il` |
| `EA` | 1 | `EA&BRQ` |
| `ED` | 1 | `{ED###` |
| `EG` | 1 | `EG\|I=B` |
| `EJ` | 1 | `2L3l~]EJ&A` |
| `EK` | 1 | `EK! ?\| ` |
| `EL` | 1 | `EL`"7&` |
| `EM0` | 1 | `ii.EM0` |
| `EPD2` | 1 | `a[EPD2` |
| `ERL` | 1 | `?ERL=N'` |
| `ES7` | 1 | `ES7\|?~` |
| `ET5` | 1 | `tJ'ET5` |
| `ETZG` | 1 | `~ETZG@\` |
| `EUU0LQ` | 1 | `@EUU0LQ` |
| `EVHS2` | 1 | `EVHS2)w` |
| `EY` | 1 | `BkX~EY@` |
| `EZ` | 1 | `,EZ}+)t` |
| `E_G` | 1 | `E_G"qj5z` |
| `F1` | 1 | `L/,F1\bV"` |
| `F1VZ` | 1 | `F1VZ+Cj` |
| `F3R` | 1 | `[&F3R[` |
| `F4` | 1 | `?p*l3\|F4` |
| `F5` | 1 | `~~Yk F5` |
| `F6` | 1 | `1+%F6 ` |
| `F8` | 1 | `/F8],4` |
| `FCWKHC` | 1 | `FCWKHC` |
| `FDO` | 1 | `FDO!&@&!:` |
| `FE` | 1 | `\|H\FE(x` |
| `FHS` | 1 | `FHS-/rYJ` |
| `FK7T` | 1 | `FK7T$w1X` |
| `FL` | 1 | `FL[NH^e-` |
| `FQ` | 1 | `R+$$FQ-<]` |
| `FQ4D` | 1 | `FQ4D<o` |
| `FRG` | 1 | `,)FRG!A` |
| `FSL` | 1 | `?FSL+4o` |
| `FW` | 1 | `LD,^`FW%` |
| `FZ` | 1 | `FZ}?l;` |
| `G1R` | 1 | `Y$G1R@t` |
| `G3` | 1 | `G3!-TkE` |
| `G6TUT` | 1 | `$G6TUT` |
| `G9` | 1 | `=J[ G9` |
| `GAD9Y` | 1 | `~GAD9Y` |
| `GB` | 1 | `GB*@M#wY` |
| `GC` | 1 | `nXg^+GC` |
| `GC3` | 1 | `GC3/VZ` |
| `GGM` | 1 | `=GGM'q` |
| `GHMAG` | 1 | `GHMAG'` |
| `GI` | 1 | `:\j`GI` |
| `GIW` | 1 | `!GIW&^` |
| `GJ` | 1 | `GJ[;YR` |
| `GL` | 1 | `<GL )vwv*JG}` |
| `GND` | 1 | `}[}GND` |
| `GP5` | 1 | `GP5\|nL` |
| `GU` | 1 | `;GU,)j` |
| `GU8P` | 1 | `GU8P=$` |
| `GVIM` | 1 | `1 g]GVIM` |
| `GX` | 1 | `GX%$'n` |
| `GXY` | 1 | `=GXY,w` |
| `H14` | 1 | `H14.xdw` |
| `H3` | 1 | `H3"}e/A` |
| `H52` | 1 | `H52@~Z` |
| `H7` | 1 | `B$H7!48_` |
| `H86` | 1 | `.H86)l` |
| `H92` | 1 | `@yp*H92` |
| `HB7` | 1 | `CQ+HB7` |
| `HC` | 1 | `'n&HC,\|` |
| `HCC` | 1 | `P'HCC'` |
| `HD` | 1 | `t![HD&W` |
| `HF` | 1 | `)B=%HF` |
| `HG` | 1 | `t!L@HG\L` |
| `HH` | 1 | `HH-JRv` |
| `HJ` | 1 | `%+#~HJ` |
| `HNDF` | 1 | `HNDF(Qi` |
| `HS` | 1 | `p$=oz#.-HS` |
| `HX1` | 1 | `&#HX1\| ` |
| `HY` | 1 | `TJ~$HY` |
| `I4` | 1 | `[6+I4/s` |
| `I8` | 1 | `?*]Z'I8` |
| `ID` | 1 | `ID!?Zv` |
| `IE` | 1 | `;A;IE$` |
| `IG` | 1 | `Y\[IG/A#Ve` |
| `IJB` | 1 | `~#@IJB]R` |
| `IL9` | 1 | `;q+IL9` |
| `IMYC` | 1 | `"}IMYC` |
| `IM_5` | 1 | `T)IM_5` |
| `IP6` | 1 | `IP6`a"` |
| `IQ` | 1 | `IQ(91J` |
| `ITCU7L` | 1 | `ITCU7L` |
| `IZ` | 1 | `IZ?C[+` |
| `J3` | 1 | `J3 hp&` |
| `J4QF` | 1 | `<.-J4QF` |
| `J5` | 1 | `J5@AVoj%E` |
| `J6` | 1 | `8I__t=-J6` |
| `J9` | 1 | `?z)#T{J9` |
| `J9_` | 1 | `'r{u&J9_` |
| `JAL` | 1 | `.JAL#oey` |
| `JE` | 1 | `zZs;JE` |
| `JG` | 1 | `<GL )vwv*JG}` |
| `JH1` | 1 | `JH1-frY` |
| `JJU` | 1 | `_*w}JJU` |
| `JL` | 1 | `)F(b,JL` |
| `JUQ` | 1 | `7-C{JUQ$` |
| `JW` | 1 | `7gp:JW` |
| `JZ` | 1 | `t~1$JZ` |
| `J_` | 1 | `Sl#J_-/` |
| `K0` | 1 | `,_B/K0` |
| `K4` | 1 | `%)K4,w` |
| `K5` | 1 | `Szr/K5:` |
| `K9` | 1 | `%Bk+K9` |
| `K9B` | 1 | `>=)\[K9B` |
| `KA` | 1 | `].KA=2` |
| `KCJNY` | 1 | `KCJNY>` |
| `KD` | 1 | `YDj"KD` |
| `KEV` | 1 | `KEV\|2&` |
| `KGFKJ` | 1 | `;\KGFKJ` |
| `KHT6` | 1 | `C*KHT6` |
| `KI` | 1 | `<<sI[$KI` |
| `KJZ` | 1 | `KJZ.pm` |
| `KK8` | 1 | `&KK8$gW` |
| `KLW` | 1 | `KLW'D$` |
| `KM` | 1 | `KM+LZ!R+:` |
| `KSB` | 1 | `KSB*em` |
| `KT` | 1 | `KT.aP-\d` |
| `KW` | 1 | `,KW~e]x` |
| `KW7` | 1 | `/y[KW7` |
| `KX` | 1 | `,KX%p6` |
| `KZ` | 1 | `<=KZ.i` |
| `L2` | 1 | `L2;`\|=` |
| `L48ZO` | 1 | `L48ZO]` |
| `L5W1` | 1 | ` )\|L5W1#` |
| `L7V` | 1 | `g?{\|L7V\|` |
| `L8B` | 1 | `L8B&%:K` |
| `LD` | 1 | `LD,^`FW%` |
| `LG` | 1 | `LG,a*ih>` |
| `LK` | 1 | `^2N]LK` |
| `LL` | 1 | `LL&%-=` |
| `LLU` | 1 | `m9[LLU` |
| `LQ` | 1 | `zz"Q(LQ~` |
| `LR` | 1 | `LR&RO'` |
| `LS` | 1 | `LS[p+3g` |
| `LT` | 1 | `,'LT}s"` |
| `LU` | 1 | `w!U'"LU` |
| `LUE` | 1 | `LUE-4g` |
| `LUZ2` | 1 | `LUZ2 &` |
| `M0` | 1 | `NIgW&M0` |
| `M1` | 1 | `M1##mHy\` |
| `M4` | 1 | `yr4?M4` |
| `M6` | 1 | `egE,i`M6` |
| `MB` | 1 | `MB<r},` |
| `MC` | 1 | `QZ>\MC` |
| `MCU` | 1 | `MCU'&0` |
| `MDB3` | 1 | `MDB3'2` |
| `MEJZ` | 1 | `G;MEJZ` |
| `MI` | 1 | `n+on@MI` |
| `MK` | 1 | `~e{[MK` |
| `ML7` | 1 | `Dz?ML7` |
| `MQ` | 1 | `MQ~wYS_` |
| `MQU` | 1 | `)%)MQU` |
| `MT` | 1 | ``MT{W&kp` |
| `MTL` | 1 | `/>MTL"` |
| `MW` | 1 | `oc],MW` |
| `MW0` | 1 | `MW0{*k.` |
| `MYC` | 1 | ` ON}MYC` |
| `MZ` | 1 | `kHL\|MZ` |
| `M_` | 1 | `M_:[88` |
| `M_DQ` | 1 | `M_DQ&#` |
| `N5` | 1 | `.wE-N5` |
| `N6` | 1 | `A./Z"N6` |
| `N89J_D` | 1 | `}"N89J_D` |
| `NATKR` | 1 | `NATKR)Zu` |
| `ND` | 1 | `(ND?!m` |
| `NH` | 1 | `FL[NH^e-` |
| `NK` | 1 | `{z`Uj5"NK` |
| `NNQ` | 1 | `}NNQ@h` |
| `NO` | 1 | `$6mk$NO\|` |
| `NOO` | 1 | `"NOO@F$DE` |
| `NP` | 1 | `bZpL+NP` |
| `NPRS` | 1 | `d[NPRS` |
| `NQ` | 1 | `NQ"ljaq)` |
| `NT` | 1 | `O5~NT&w` |
| `NU70` | 1 | ` NU70<` |
| `O1CI` | 1 | `O1CI-5` |
| `O3O` | 1 | `O3O[Ud` |
| `O6` | 1 | `R~O6@~` |
| `O60` | 1 | `DmJ)%O60` |
| `OD` | 1 | `Ud=OD?` |
| `OE` | 1 | `;OE/*z` |
| `OF` | 1 | `9&9+OF` |
| `OGW3` | 1 | `Ge.OGW3` |
| `OHLG` | 1 | `OHLG^)<=` |
| `OI` | 1 | `@t<OI& {` |
| `OIW` | 1 | `OIW$NW` |
| `OK` | 1 | `OK:@96` |
| `OLH` | 1 | `"L/OLH` |
| `OM` | 1 | `AQ`OM}v` |
| `OO` | 1 | `OO?d[Ty` |
| `ORO` | 1 | `!fM&ORO` |
| `OS7` | 1 | `=OS7;R` |
| `OW` | 1 | `^7K.OW` |
| `OZQ8` | 1 | `aFd{OZQ8` |
| `P2` | 1 | `A"P2]::x` |
| `P3` | 1 | `R>P3'w` |
| `P9` | 1 | `/P9:k'Y` |
| `PD` | 1 | `PD\1nf` |
| `PF` | 1 | `PF*A)2` |
| `PH` | 1 | `PH#t=v` |
| `PI` | 1 | `nQ)PI>` |
| `PL` | 1 | `PL-Fc=` |
| `PO` | 1 | `PO`s9k` |
| `PQA7AT` | 1 | `"PQA7AT\d` |
| `PV` | 1 | `h3~ PV` |
| `PY23G` | 1 | `PY23G*` |
| `PYD` | 1 | `\PYD*`` |
| `PYP` | 1 | `PYP<^<` |
| `PZ` | 1 | `L&PZ$b-` |
| `P_` | 1 | `Q>'P_,3t` |
| `Q1Z` | 1 | `Q1Z{fm` |
| `Q4_S` | 1 | `,{Q4_S` |
| `Q5` | 1 | `-Q5=mp` |
| `Q7C` | 1 | `_ (k+Q7C` |
| `QB` | 1 | `MIBx@QB` |
| `QD` | 1 | `r%#>QD` |
| `QFF` | 1 | `;;s}QFF` |
| `QO` | 1 | `QO 0 }` |
| `QQ` | 1 | `QQ.QP+` |
| `QY` | 1 | `QY$?'m%z` |
| `QZ` | 1 | `QZ>\MC` |
| `R1` | 1 | `5#H^R1` |
| `R3K` | 1 | `R3K~).V}77,` |
| `R4` | 1 | `G;1,m\R4` |
| `R5` | 1 | `hE%T,R5` |
| `R5J` | 1 | `R5J"5S` |
| `RAK` | 1 | `-RAK?<T` |
| `RE7` | 1 | `RE7,\|$` |
| `RF` | 1 | ``$RF.O0` |
| `RI` | 1 | `u4<k{W,]RI` |
| `RO` | 1 | `LR&RO'` |
| `RS` | 1 | `/RS>((` |
| `RT` | 1 | `e1k]g<Sm+RT^j` |
| `R_E` | 1 | `R_E(dR` |
| `S0Y6F` | 1 | `(S0Y6F` |
| `S1V` | 1 | `S1V }i` |
| `S2Q1` | 1 | `S2Q1#/` |
| `S4` | 1 | `u/&}S4` |
| `SB6` | 1 | `}SB6{0` |
| `SF` | 1 | `.FS)SF` |
| `SI` | 1 | `'h#`SI` |
| `SJ` | 1 | `S\SJ#`(ZSH!` |
| `SK` | 1 | `=SK>Q`` |
| `SLMOPK` | 1 | `SLMOPK` |
| `SO` | 1 | `@(*,SO\O` |
| `ST` | 1 | `*P!p&ST` |
| `SV` | 1 | `SV#L"/[Y` |
| `SX` | 1 | `gpp=SX` |
| `SX5` | 1 | `SX5$"N` |
| `SYP` | 1 | `gX~SYP` |
| `S_LL` | 1 | `3&S_LL` |
| `T3EA` | 1 | `Fy;T3EA/` |
| `T4` | 1 | `j"s{T4` |
| `T6` | 1 | `r4qD T6` |
| `T9` | 1 | `?ZvB<T9` |
| `TB` | 1 | `TB^npP` |
| `TG` | 1 | `}TG{3,` |
| `TJ8` | 1 | `HA:TJ8+` |
| `TPYFHD` | 1 | `TPYFHD` |
| `TS` | 1 | `TS> Mga` |
| `TTID` | 1 | `<%TTID` |
| `TY6` | 1 | `=/,TY6` |
| `TZW7N_` | 1 | `TZW7N_` |
| `U3QR` | 1 | `U3QR A-k] ^` |
| `U4` | 1 | `U4[6X!g` |
| `U5` | 1 | `;41'U5\eV` |
| `U7` | 1 | `U7\|PX^` |
| `U78` | 1 | `1R0'U78` |
| `UB` | 1 | `gJU[UB` |
| `UC` | 1 | `+8m{UC` |
| `UJ` | 1 | `-j\UJ^` |
| `UN` | 1 | `UN`wLv` |
| `UR` | 1 | `hI!UR'` |
| `URZ` | 1 | `/!URZ#` |
| `UU` | 1 | `A`UU,^` |
| `UV` | 1 | `UV-Kfp` |
| `UW` | 1 | `UW"H $` |
| `V2` | 1 | `Zd9&V2` |
| `V5` | 1 | `V5!Ieg` |
| `V7` | 1 | `%)V7{Wo` |
| `V9` | 1 | `V9-w_t` |
| `VA` | 1 | `fw=]VA)` |
| `VES` | 1 | `VES{/usk` |
| `VG` | 1 | ``<VG! ` |
| `VGL` | 1 | `VGL\|v<` |
| `VN157R` | 1 | `VN157R` |
| `VOU` | 1 | `VOU`.#2` |
| `VQ` | 1 | `VQ>Fmx` |
| `VR` | 1 | `VR#!>2[` |
| `VS` | 1 | `DTQ+VS` |
| `VV8` | 1 | `VV8*q0o` |
| `VX` | 1 | `B)F[VX` |
| `VZ` | 1 | `GC3/VZ` |
| `W2` | 1 | `ZA5[W2` |
| `W3` | 1 | `"W3\sDDXx?` |
| `W4A` | 1 | ``$W4A@~` |
| `W9` | 1 | `W9**<n` |
| `WH` | 1 | `g$u>k;WH` |
| `WJ` | 1 | `"Z"WJ*` |
| `WL` | 1 | `1s;-:WL` |
| `WO` | 1 | `}&!)%WO` |
| `WPKBHF` | 1 | `WPKBHF` |
| `WQ9` | 1 | `~WQ9<H` |
| `WSU` | 1 | `dE[WSU%LN` |
| `WX` | 1 | `K(&.WX` |
| `X0D` | 1 | `%X0D!T` |
| `X7` | 1 | `X7%wkii` |
| `XFL` | 1 | `kj%/XFL` |
| `XI` | 1 | `{>XI-'0` |
| `XJ` | 1 | `el?8?XJ` |
| `XK` | 1 | `i^XK)W` |
| `XKT` | 1 | `XKT&9b` |
| `XN_` | 1 | `$XN_,u` |
| `XRWF` | 1 | `X*XRWF`` |
| `XTV` | 1 | `[^]XTV` |
| `XW` | 1 | `~?`XW/` |
| `XXUS` | 1 | `XXUS~_` |
| `Y3HP4` | 1 | `Y3HP4'` |
| `Y4` | 1 | `a8#Y4/` |
| `Y6` | 1 | `x9?Y6(` |
| `Y7Y1H` | 1 | `9t{Y7Y1H` |
| `YCB` | 1 | `YCB&c\|n` |
| `YG` | 1 | `z&`YG]` |
| `YJ_` | 1 | `0k)YJ_` |
| `YLI` | 1 | `YLI))[` |
| `YR` | 1 | `GJ[;YR` |
| `YRUS` | 1 | `YRUS=?` |
| `YT` | 1 | `YT!]0A` |
| `YV` | 1 | `YV}1?U` |
| `YYYB` | 1 | ` ^YYYB` |
| `Z0` | 1 | `'Z0(8M?=` |
| `ZA` | 1 | `pLm*ZA` |
| `ZA5` | 1 | `ZA5[W2` |
| `ZAVK` | 1 | ``ZAVK^2A` |
| `ZF` | 1 | `(lg%ZF>^` |
| `ZL5` | 1 | `ZL5<s5` |
| `ZO3IQF` | 1 | `ZO3IQF` |
| `ZOQO` | 1 | `(ZOQO:'` |
| `ZP` | 1 | `vEC{ZP` |
| `ZS` | 1 | `>j6]c%ZS` |
| `ZSH` | 1 | `S\SJ#`(ZSH!` |
| `ZX` | 1 | `?ZX>}:` |
| `ZYBNZ` | 1 | `&ZYBNZ` |
| `Z_` | 1 | `Z_\#m-),4\` |

## Known commands NOT seen as standalone tokens

- `APR` (no match)
- `AST` (no match)
- `AVD` (no match)
- `DQK` (no match)
- `DTM` (no match)
- `FQK` (no match)
- `GCS` (no match)
- `GLG` (no match)
- `GLT` (no match)
- `GSI` (no match)
- `GST` (no match)
- `GWF` (no match)
- `HLD` (no match)
- `JNT` (no match)
- `JPM` (no match)
- `KAL` (no match)
- `KEY` (no match)
- `LCR` (no match)
- `MDL` (no match)
- `MNU` (no match)
- `MSB` (no match)
- `MSI` (no match)
- `MSV` (no match)
- `NXT` (no match)
- `POF` (no match)
- `PRV` (no match)
- `PSI` (no match)
- `PWF` (no match)
- `PWR` (no match)
- `QSH` (no match)
- `SQK` (no match)
- `SQL` (no match)
- `STS` (no match)
- `SVC` (no match)
- `URC` (no match)
- `VER` (no match)
- `VOL` (no match)
